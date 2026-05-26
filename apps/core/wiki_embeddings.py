import hashlib
import logging
import math

from django.conf import settings
from django.utils import timezone

from .models import WikiDocumentEmbedding
from .wiki_markdown import strip_leading_title_heading

logger = logging.getLogger(__name__)

WIKI_EMBEDDING_PROVIDER_OPENAI = "openai"
WIKI_EMBEDDING_PROVIDER_SOURCE_CENTROID = "source_chunk_centroid"
WIKI_EMBEDDING_VECTOR_DIMENSIONS = 1536

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised when dependency is unavailable
    OpenAI = None


def sync_wiki_document_embedding(document):
    if document.current_revision_id is None:
        return None

    embedding_model = settings.WIKI_EMBEDDING_MODEL
    embedding_dimensions = settings.WIKI_EMBEDDING_DIM
    content_hash = _build_wiki_embedding_content_hash(document)
    existing_embedding = (
        document.embeddings.filter(embedding_model=embedding_model)
        .select_related("wiki_revision")
        .first()
    )
    if (
        existing_embedding is not None
        and existing_embedding.wiki_revision_id == document.current_revision_id
        and existing_embedding.content_hash == content_hash
    ):
        return existing_embedding

    vector = _generate_wiki_embedding_vector(document, embedding_model=embedding_model)
    provider = WIKI_EMBEDDING_PROVIDER_OPENAI
    if vector is None:
        vector = _get_source_chunk_embedding_centroid(
            document,
            embedding_model=embedding_model,
        )
        provider = WIKI_EMBEDDING_PROVIDER_SOURCE_CENTROID
    if vector is None:
        logger.info(
            "wiki_embedding_unavailable wiki_document_id=%s revision_id=%s embedding_model=%s",
            document.pk,
            document.current_revision_id,
            embedding_model,
        )
        return None

    if embedding_dimensions != WIKI_EMBEDDING_VECTOR_DIMENSIONS:
        logger.warning(
            "wiki_embedding_config_dimension_mismatch configured_dimension=%s supported_dimension=%s",
            embedding_dimensions,
            WIKI_EMBEDDING_VECTOR_DIMENSIONS,
        )
        return None

    if len(vector) != embedding_dimensions:
        logger.warning(
            "wiki_embedding_dimension_mismatch wiki_document_id=%s revision_id=%s embedding_model=%s dimension=%s",
            document.pk,
            document.current_revision_id,
            embedding_model,
            len(vector),
        )
        return None

    embedding, _ = WikiDocumentEmbedding.objects.update_or_create(
        wiki_document=document,
        embedding_model=embedding_model,
        defaults={
            "wiki_revision": document.current_revision,
            "embedding_dim": len(vector),
            "embedding": vector,
            "content_hash": content_hash,
            "provider": provider,
            "updated_at": timezone.now(),
        },
    )
    return embedding


def get_document_embedding_vector(document, *, embedding_model: str | None = None):
    model_name = embedding_model or settings.WIKI_EMBEDDING_MODEL
    embedding = next(
        (
            item
            for item in getattr(document, "_prefetched_objects_cache", {}).get(
                "embeddings", []
            )
            if item.embedding_model == model_name
        ),
        None,
    )
    if embedding is None:
        embedding = document.embeddings.filter(embedding_model=model_name).first()
    if embedding is None:
        return None
    return parse_embedding_vector(embedding.embedding)


def parse_embedding_vector(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped[0] == "[" and stripped[-1] == "]":
            stripped = stripped[1:-1]
        if not stripped:
            return None
        return [float(item.strip()) for item in stripped.split(",") if item.strip()]
    return None


def cosine_similarity(left_vector, right_vector):
    if not left_vector or not right_vector or len(left_vector) != len(right_vector):
        return None
    numerator = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left_vector, right_vector, strict=True):
        numerator += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm <= 0 or right_norm <= 0:
        return None
    return numerator / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _generate_wiki_embedding_vector(document, *, embedding_model: str):
    if not settings.OPENAI_API_KEY or OpenAI is None:
        return None

    embedding_input = _build_wiki_embedding_input(document)
    if not embedding_input:
        return None

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.embeddings.create(
            input=embedding_input,
            model=embedding_model,
            dimensions=settings.WIKI_EMBEDDING_DIM,
        )
    except Exception:
        logger.exception(
            "wiki_embedding_generation_failed wiki_document_id=%s revision_id=%s embedding_model=%s",
            document.pk,
            document.current_revision_id,
            embedding_model,
        )
        return None
    return list(response.data[0].embedding)


def _build_wiki_embedding_input(document):
    revision = document.current_revision
    if revision is None:
        return ""
    body = strip_leading_title_heading(
        revision.content_markdown, document.title
    ).strip()
    return "\n\n".join(
        part
        for part in (
            document.title.strip(),
            document.summary.strip(),
            body,
        )
        if part
    )


def _build_wiki_embedding_content_hash(document):
    content = _build_wiki_embedding_input(document)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_source_chunk_embedding_centroid(document, *, embedding_model: str):
    revision = document.current_revision
    if revision is None:
        return None

    vectors = []
    seen_chunk_ids = set()
    for revision_source in revision.sources.select_related(
        "source_chunk"
    ).prefetch_related("source_chunk__embeddings"):
        source_chunk = revision_source.source_chunk
        if source_chunk.pk in seen_chunk_ids:
            continue
        seen_chunk_ids.add(source_chunk.pk)
        embedding = next(
            (
                chunk_embedding
                for chunk_embedding in source_chunk.embeddings.all()
                if chunk_embedding.embedding_model == embedding_model
            ),
            None,
        )
        if embedding is None:
            continue
        parsed_vector = parse_embedding_vector(embedding.embedding)
        if parsed_vector is None:
            continue
        vectors.append(parsed_vector)

    if not vectors:
        return None

    dimension = len(vectors[0])
    centroid = [0.0] * dimension
    valid_vector_count = 0
    for vector in vectors:
        if len(vector) != dimension:
            continue
        valid_vector_count += 1
        for index, value in enumerate(vector):
            centroid[index] += value
    if valid_vector_count == 0:
        return None
    return [value / valid_vector_count for value in centroid]
