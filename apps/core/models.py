import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .community_content import (
    extract_post_render_parts,
)


class TagType(models.TextChoices):
    USER = "user", "User"
    SYSTEM = "system", "System"


class PostStatus(models.TextChoices):
    PUBLISHED = "published", "Published"
    DRAFT = "draft", "Draft"


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
            if len(value) != self.dimensions:
                raise ValidationError(
                    f"Expected {self.dimensions} embedding dimensions, got {len(value)}."
                )
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
    tag_type = PostgresEnumField(
        max_length=20,
        enum_type="tag_type",
        choices=TagType.choices,
        default=TagType.USER,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "tags"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Post(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author_user = models.ForeignKey(
        "accounts.HiveUser",
        on_delete=models.SET_NULL,
        related_name="posts",
        db_column="author_user_id",
        blank=True,
        null=True,
    )
    content_markdown = models.TextField()
    title_cache = models.CharField(max_length=255, blank=True, default="")
    body_markdown_cache = models.TextField(blank=True, default="")
    summary_cache = models.TextField(blank=True, default="")
    status = PostgresEnumField(
        max_length=20,
        enum_type="post_status",
        choices=PostStatus.choices,
        default=PostStatus.PUBLISHED,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(blank=True, null=True)
    likes = models.ManyToManyField(
        "accounts.HiveUser",
        through="PostLike",
        related_name="liked_posts",
    )
    tags = models.ManyToManyField(
        Tag,
        through="PostTag",
        related_name="posts",
    )
    wiki_documents = models.ManyToManyField(
        "WikiDocument",
        through="PostWikiDocument",
        related_name="community_posts",
    )

    class Meta:
        db_table = "posts"

    def __str__(self):
        return self.summary or str(self.pk)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("community_detail", kwargs={"post_id": self.pk})

    def sync_cached_content_fields(self):
        source = self.content_markdown or ""
        title, body_markdown, summary = extract_post_render_parts(source)
        self.title_cache = title
        self.body_markdown_cache = body_markdown
        self.summary_cache = summary
        self.__dict__["_cached_content_markdown_source"] = source

    def _cached_fields_match_source(self) -> bool:
        return self.__dict__.get("_cached_content_markdown_source") == (
            self.content_markdown or ""
        )

    def save(self, *args, **kwargs):
        self.sync_cached_content_fields()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "title_cache",
                "body_markdown_cache",
                "summary_cache",
            }
        super().save(*args, **kwargs)

    @property
    def title(self) -> str:
        if self.content_markdown and not self._cached_fields_match_source():
            self.sync_cached_content_fields()
        return self.title_cache

    @property
    def body_markdown(self) -> str:
        if self.content_markdown and not self._cached_fields_match_source():
            self.sync_cached_content_fields()
        return self.body_markdown_cache

    @property
    def summary(self) -> str:
        if self.content_markdown and not self._cached_fields_match_source():
            self.sync_cached_content_fields()
        return self.summary_cache

    @property
    def url(self) -> str:
        return self.get_absolute_url()

    @property
    def author(self) -> str:
        return self.author_user.username if self.author_user else "익명 사용자"


class PostLike(models.Model):
    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="post_likes",
        db_column="post_id",
    )
    user = models.ForeignKey(
        "accounts.HiveUser",
        on_delete=models.CASCADE,
        related_name="post_likes",
        db_column="user_id",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "post_likes"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"],
                name="post_likes_post_id_user_id_key",
            )
        ]


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="comments",
        db_column="post_id",
    )
    author_user = models.ForeignKey(
        "accounts.HiveUser",
        on_delete=models.SET_NULL,
        related_name="comments",
        db_column="author_user_id",
        blank=True,
        null=True,
    )
    parent_comment = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="replies",
        db_column="parent_comment_id",
        blank=True,
        null=True,
    )
    content = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(blank=True, null=True)
    likes = models.ManyToManyField(
        "accounts.HiveUser",
        through="CommentLike",
        related_name="liked_comments",
    )

    class Meta:
        db_table = "comments"

    def __str__(self):
        return f"Comment<{self.pk}>"


class CommentLike(models.Model):
    id = models.BigAutoField(primary_key=True)
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="comment_likes",
        db_column="comment_id",
    )
    user = models.ForeignKey(
        "accounts.HiveUser",
        on_delete=models.CASCADE,
        related_name="comment_likes",
        db_column="user_id",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "comment_likes"
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "user"],
                name="comment_likes_comment_id_user_id_key",
            )
        ]


class PostTag(models.Model):
    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="post_tags",
        db_column="post_id",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        related_name="post_tags",
        db_column="tag_id",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "post_tags"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "tag"],
                name="post_tags_post_id_tag_id_key",
            )
        ]


class PostWikiDocument(models.Model):
    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="post_wiki_documents",
        db_column="post_id",
    )
    wiki_document = models.ForeignKey(
        "WikiDocument",
        on_delete=models.CASCADE,
        related_name="post_wiki_documents",
        db_column="wiki_document_id",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "post_wiki_documents"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "wiki_document"],
                name="post_wiki_documents_post_id_wiki_document_id_key",
            )
        ]


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
