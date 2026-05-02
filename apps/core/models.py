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
