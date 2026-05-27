import uuid

import django.db.models.deletion
import django.utils.timezone
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models

import apps.core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        CreateExtension("vector"),
        migrations.RunSQL(
            sql=(
                "CREATE TYPE wiki_document_status AS ENUM "
                "('published', 'archived', 'deleted');"
            ),
            reverse_sql="DROP TYPE wiki_document_status;",
        ),
        migrations.RunSQL(
            sql="CREATE TYPE wiki_generation_type AS ENUM ('ai', 'human');",
            reverse_sql="DROP TYPE wiki_generation_type;",
        ),
        migrations.CreateModel(
            name="ChunkEmbedding",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("embedding_model", models.CharField(max_length=100)),
                ("embedding_dim", models.IntegerField()),
                ("embedding", apps.core.models.VectorField(dimensions=1536)),
                (
                    "content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "source_chunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="embeddings",
                        to="core.sourcechunk",
                    ),
                ),
            ],
            options={
                "db_table": "chunk_embeddings",
            },
        ),
        migrations.CreateModel(
            name="WikiDocument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("slug", models.CharField(max_length=255, unique=True)),
                ("summary", models.TextField()),
                (
                    "status",
                    apps.core.models.PostgresEnumField(
                        choices=[
                            ("published", "Published"),
                            ("archived", "Archived"),
                            ("deleted", "Deleted"),
                        ],
                        default="published",
                        enum_type="wiki_document_status",
                        max_length=20,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "wiki_documents",
            },
        ),
        migrations.CreateModel(
            name="WikiRevision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("revision_number", models.IntegerField()),
                ("content_markdown", models.TextField()),
                (
                    "generation_type",
                    apps.core.models.PostgresEnumField(
                        choices=[("ai", "AI"), ("human", "Human")],
                        default="ai",
                        enum_type="wiki_generation_type",
                        max_length=20,
                    ),
                ),
                (
                    "generation_model",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "wiki_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="core.wikidocument",
                    ),
                ),
            ],
            options={
                "db_table": "wiki_revisions",
            },
        ),
        migrations.CreateModel(
            name="WikiRevisionSource",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("evidence_text", models.TextField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "source_chunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="wiki_revision_sources",
                        to="core.sourcechunk",
                    ),
                ),
                (
                    "wiki_revision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sources",
                        to="core.wikirevision",
                    ),
                ),
            ],
            options={
                "db_table": "wiki_revision_sources",
            },
        ),
        migrations.AddField(
            model_name="wikidocument",
            name="current_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="core.wikirevision",
            ),
        ),
        migrations.AddConstraint(
            model_name="chunkembedding",
            constraint=models.UniqueConstraint(
                fields=("source_chunk", "embedding_model"),
                name="uq_chunk_embeddings_source_chunk_model",
            ),
        ),
        migrations.AddConstraint(
            model_name="wikirevision",
            constraint=models.UniqueConstraint(
                fields=("wiki_document", "revision_number"),
                name="uq_wiki_revisions_document_revision",
            ),
        ),
    ]
