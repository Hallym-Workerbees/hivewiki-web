from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ChunkEmbedding, WikiDocument, WikiRevision, WikiRevisionSource
from .wiki_embeddings import sync_wiki_document_embedding


def _schedule_sync(document_id):
    sync_wiki_document_embedding(
        WikiDocument.objects.select_related("current_revision")
        .prefetch_related("embeddings")
        .get(pk=document_id)
    )


@receiver(post_save, sender=WikiDocument)
def sync_wiki_embedding_on_document_save(
    sender, instance, created, update_fields, raw, **kwargs
):
    if raw or instance.current_revision_id is None:
        return
    tracked_fields = {"current_revision", "title", "summary"}
    if update_fields is not None and tracked_fields.isdisjoint(set(update_fields)):
        return
    _schedule_sync(instance.pk)


@receiver(post_save, sender=WikiRevision)
def sync_wiki_embedding_on_current_revision_save(sender, instance, raw, **kwargs):
    if raw:
        return
    if not WikiDocument.objects.filter(
        pk=instance.wiki_document_id,
        current_revision_id=instance.pk,
    ).exists():
        return
    _schedule_sync(instance.wiki_document_id)


@receiver(post_save, sender=WikiRevisionSource)
@receiver(post_delete, sender=WikiRevisionSource)
def sync_wiki_embedding_on_revision_source_change(sender, instance, **kwargs):
    if not WikiDocument.objects.filter(
        pk=instance.wiki_revision.wiki_document_id,
        current_revision_id=instance.wiki_revision_id,
    ).exists():
        return
    _schedule_sync(instance.wiki_revision.wiki_document_id)


@receiver(post_save, sender=ChunkEmbedding)
@receiver(post_delete, sender=ChunkEmbedding)
def sync_wiki_embedding_on_chunk_embedding_change(sender, instance, **kwargs):
    document_ids = list(
        WikiDocument.objects.filter(
            current_revision__sources__source_chunk_id=instance.source_chunk_id
        )
        .values_list("id", flat=True)
        .distinct()
    )
    for document_id in document_ids:
        _schedule_sync(document_id)
