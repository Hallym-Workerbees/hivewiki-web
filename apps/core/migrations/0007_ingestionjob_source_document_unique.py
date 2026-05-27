from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_postbookmark_wikibookmark_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="ingestionjob",
            constraint=models.UniqueConstraint(
                fields=("source_document",),
                name="ingestion_jobs_source_document_id_key",
            ),
        ),
    ]
