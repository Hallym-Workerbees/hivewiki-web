from django.db.models import Q
from django.urls import reverse

from .models import WikiDocument, WikiDocumentStatus


def get_wiki_search_results(*, query="", limit=12):
    documents = (
        WikiDocument.objects.filter(status=WikiDocumentStatus.PUBLISHED)
        .select_related("current_revision")
        .order_by("-updated_at")
    )
    normalized_query = query.strip()
    if normalized_query:
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
