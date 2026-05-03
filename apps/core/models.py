import uuid

from django.db import models
from django.utils import timezone


class TagType(models.TextChoices):
    USER = "user", "User"
    SYSTEM = "system", "System"


class IngestionJobStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    STARTED = "STARTED", "Started"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class SourceDocumentFetchStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    FETCHED = "FETCHED", "Fetched"
    FAILED = "FAILED", "Failed"


class SourceDocumentWikiStatus(models.TextChoices):
    NOT_REQUESTED = "NOT_REQUESTED", "Not requested"
    REQUESTED = "REQUESTED", "Requested"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class WikiDocumentStatus(models.TextChoices):
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"
    DELETED = "deleted", "Deleted"


class WikiGenerationType(models.TextChoices):
    AI = "ai", "AI"
    HUMAN = "human", "Human"


class VectorField(models.Field):
    description = "PostgreSQL vector field"

    def __init__(self, *args, dimensions, **kwargs):
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return f"vector({self.dimensions})"

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["dimensions"] = self.dimensions
        return name, path, args, kwargs

    def get_internal_type(self):
        return "TextField"

    def get_prep_value(self, value):
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return "[" + ",".join(str(float(item)) for item in value) + "]"
        return str(value)


class PostgresEnumField(models.CharField):
    def __init__(self, *args, enum_type, **kwargs):
        self.enum_type = enum_type
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return self.enum_type

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["enum_type"] = self.enum_type
        return name, path, args, kwargs


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50, unique=True)
    tag_type = models.CharField(
        max_length=20,
        choices=TagType.choices,
        default=TagType.USER,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "tags"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Source(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField()
    target_url = models.TextField()
    enabled = models.BooleanField(default=True)
    poll_interval_minutes = models.IntegerField(default=30)
    next_poll_at = models.DateTimeField(default=timezone.now)
    initial_backfill_done = models.BooleanField(default=False)
    backfill_completed_at = models.DateTimeField(blank=True, null=True)
    last_polled_at = models.DateTimeField(blank=True, null=True)
    last_success_at = models.DateTimeField(blank=True, null=True)
    last_error_at = models.DateTimeField(blank=True, null=True)
    last_error_message = models.TextField(blank=True, null=True)
    consecutive_failures = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "sources"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SourceDocument(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(
        Source,
        on_delete=models.CASCADE,
        related_name="documents",
        db_column="source_id",
    )
    canonical_url = models.TextField()
    title = models.TextField()
    published_at = models.DateTimeField(blank=True, null=True)
    body_text = models.TextField(blank=True, null=True)
    fetch_status = models.CharField(
        max_length=20,
        choices=SourceDocumentFetchStatus.choices,
        default=SourceDocumentFetchStatus.PENDING,
    )
    fetch_retry_count = models.IntegerField(default=0)
    fetch_error_message = models.TextField(blank=True, null=True)
    wiki_status = models.CharField(
        max_length=20,
        choices=SourceDocumentWikiStatus.choices,
        default=SourceDocumentWikiStatus.NOT_REQUESTED,
    )
    collected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "source_documents"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "canonical_url"],
                name="source_documents_source_id_canonical_url_key",
            )
        ]

    def __str__(self):
        return self.title


class IngestionJob(models.Model):
    id = models.BigAutoField(primary_key=True)
    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.CASCADE,
        related_name="ingestion_jobs",
        db_column="source_document_id",
    )
    status = models.CharField(
        max_length=20,
        choices=IngestionJobStatus.choices,
        default=IngestionJobStatus.QUEUED,
    )
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    queued_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "ingestion_jobs"


class SourceChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
        db_column="source_document_id",
    )
    chunk_index = models.IntegerField()
    chunk_type = models.CharField(max_length=30, blank=True, null=True)
    section_title = models.TextField(blank=True, null=True)
    content_text = models.TextField()
    token_count = models.IntegerField(blank=True, null=True)
    char_start = models.IntegerField(blank=True, null=True)
    char_end = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "source_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["source_document", "chunk_index"],
                name="uq_source_chunks_document_chunk_index",
            )
        ]


class ChunkEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_chunk = models.ForeignKey(
        SourceChunk,
        on_delete=models.CASCADE,
        related_name="embeddings",
    )
    embedding_model = models.CharField(max_length=100)
    embedding_dim = models.IntegerField()
    embedding = VectorField(dimensions=1536)
    content_hash = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "chunk_embeddings"
        constraints = [
            models.UniqueConstraint(
                fields=["source_chunk", "embedding_model"],
                name="uq_chunk_embeddings_source_chunk_model",
            )
        ]


class WikiDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, unique=True)
    summary = models.TextField()
    current_revision = models.ForeignKey(
        "WikiRevision",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    status = PostgresEnumField(
        max_length=20,
        enum_type="wiki_document_status",
        choices=WikiDocumentStatus.choices,
        default=WikiDocumentStatus.PUBLISHED,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "wiki_documents"

    def __str__(self):
        return self.title


class WikiRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wiki_document = models.ForeignKey(
        WikiDocument,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    revision_number = models.IntegerField()
    content_markdown = models.TextField()
    generation_type = PostgresEnumField(
        max_length=20,
        enum_type="wiki_generation_type",
        choices=WikiGenerationType.choices,
        default=WikiGenerationType.AI,
    )
    generation_model = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "wiki_revisions"
        constraints = [
            models.UniqueConstraint(
                fields=["wiki_document", "revision_number"],
                name="uq_wiki_revisions_document_revision",
            )
        ]


class WikiRevisionSource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wiki_revision = models.ForeignKey(
        WikiRevision,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    source_chunk = models.ForeignKey(
        SourceChunk,
        on_delete=models.RESTRICT,
        related_name="wiki_revision_sources",
    )
    evidence_text = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "wiki_revision_sources"
