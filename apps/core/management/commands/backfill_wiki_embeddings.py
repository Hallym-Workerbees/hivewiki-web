from django.core.management.base import BaseCommand

from apps.core.models import WikiDocument
from apps.core.wiki_embeddings import sync_wiki_document_embedding


class Command(BaseCommand):
    help = "Backfill embeddings for published wiki documents with a current revision."

    def handle(self, *args, **options):
        queryset = (
            WikiDocument.objects.select_related("current_revision")
            .prefetch_related("embeddings")
            .filter(current_revision__isnull=False)
            .order_by("title")
        )
        synced_count = 0
        skipped_count = 0
        for document in queryset.iterator():
            embedding = sync_wiki_document_embedding(document)
            if embedding is None:
                skipped_count += 1
                continue
            synced_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {synced_count} wiki embeddings. "
                f"Skipped {skipped_count} documents without available vectors."
            )
        )
