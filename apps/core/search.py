from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import Count, Q
from django.urls import reverse

from .models import Post, PostStatus, WikiDocument, WikiDocumentStatus


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


def get_post_search_results(*, query="", limit=12):
    posts = (
        Post.objects.filter(status=PostStatus.PUBLISHED, deleted_at__isnull=True)
        .select_related("author_user")
        .prefetch_related("tags", "wiki_documents")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__deleted_at__isnull=True),
                distinct=True,
            ),
            like_count=Count("post_likes__user", distinct=True),
        )
        .order_by("-created_at", "-id")
    )
    normalized_query = query.strip()
    if normalized_query:
        if connection.vendor == "postgresql":
            search_vector = (
                SearchVector("title_cache", weight="A", config="simple")
                + SearchVector("summary_cache", weight="B", config="simple")
                + SearchVector("body_markdown_cache", weight="C", config="simple")
            )
            search_query = SearchQuery(
                normalized_query,
                config="simple",
                search_type="websearch",
            )
            posts = posts.annotate(
                search_vector=search_vector,
                search_rank=SearchRank(search_vector, search_query),
            ).filter(
                Q(search_vector=search_query)
                | Q(tags__name__icontains=normalized_query)
                | Q(wiki_documents__title__icontains=normalized_query)
            )
            posts = posts.distinct().order_by(
                "-search_rank", "-comment_count", "-created_at", "-id"
            )
        else:
            posts = posts.filter(
                Q(title_cache__icontains=normalized_query)
                | Q(summary_cache__icontains=normalized_query)
                | Q(body_markdown_cache__icontains=normalized_query)
                | Q(tags__name__icontains=normalized_query)
                | Q(wiki_documents__title__icontains=normalized_query)
            ).distinct()

    total_count = posts.count()
    return {
        "query": normalized_query,
        "total_count": total_count,
        "items": list(posts[:limit]),
    }
