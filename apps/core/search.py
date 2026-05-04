from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import Q
from django.urls import reverse

from .models import WikiDocument, WikiDocumentStatus


def get_wiki_search_results(*, query="", limit=12):
    documents = (
        WikiDocument.objects.filter(
            status=WikiDocumentStatus.PUBLISHED,
            current_revision__isnull=False,
        )
        .select_related("current_revision")
        .order_by("-updated_at")
    )
    normalized_query = query.strip()
    if normalized_query:
        if connection.vendor == "postgresql":
            search_vector = (
                SearchVector("title", weight="A", config="simple")
                + SearchVector("summary", weight="B", config="simple")
                + SearchVector(
                    "current_revision__content_markdown",
                    weight="C",
                    config="simple",
                )
            )
            search_query = SearchQuery(
                normalized_query,
                config="simple",
                search_type="websearch",
            )
            documents = documents.annotate(
                search_vector=search_vector,
                search_rank=SearchRank(search_vector, search_query),
            ).filter(search_vector=search_query)
            documents = documents.order_by("-search_rank", "-updated_at")
        else:
            documents = documents.filter(
                Q(title__icontains=normalized_query)
                | Q(summary__icontains=normalized_query)
                | Q(current_revision__content_markdown__icontains=normalized_query)
            )

    total_count = documents.count()
    documents = list(documents[:limit])
    return {
        "query": normalized_query,
        "total_count": total_count,
        "items": [
            {
                "category": "문서",
                "updated_at": document.updated_at,
                "title": document.title,
                "summary": document.summary,
                "tags": [],
                "url": reverse("wiki_detail", kwargs={"slug": document.slug}),
            }
            for document in documents
        ],
    }
