import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import admin_required, login_required
from apps.accounts.models import HiveUser, OAuthAccount, UserRole, UserStatus
from apps.accounts.services import purge_user_sessions

from .community_content import extract_linked_wiki_slugs
from .forms import CommentForm, PostForm, SourceForm, TagForm
from .markdown_rendering import get_cached_revision_render
from .models import (
    Comment,
    CommentStatus,
    IngestionJob,
    Post,
    PostStatus,
    Source,
    SourceDocument,
    Tag,
    WikiDocument,
    WikiDocumentStatus,
)
from .search import get_wiki_search_results
from .wiki_markdown import strip_leading_title_heading

logger = logging.getLogger(__name__)
COMMUNITY_FEED_PAGE_SIZE = 10

ADMIN_USER_ACTIONS = frozenset(
    {
        "promote_admin",
        "demote_admin",
        "suspend",
        "activate",
        "delete",
    }
)

LIST_TAGS = ["지식", "협업", "캠퍼스"]

FEATURED_WIKI = [
    {
        "category": "문서",
        "updated_at": "5분 전",
        "title": "캡스톤 위키 운영 가이드",
        "summary": "프로젝트 문서를 어떻게 축적하고 연결할지에 대한 기본 원칙과 운영 흐름을 정리한 문서입니다.",
        "tags": ["운영", "가이드", "온보딩"],
        "url": "/wiki/",
    },
    {
        "category": "요약",
        "updated_at": "오늘",
        "title": "커뮤니티 질문을 문서로 전환하는 기준",
        "summary": "질문, 답변, 회고를 어떤 조건에서 위키 문서로 승격할지에 대한 실무 기준을 정리합니다.",
        "tags": ["정책", "정리", "문서화"],
        "url": "/wiki/",
    },
]

FEATURED_POSTS = [
    {
        "author": "제품팀",
        "created_at": "방금 전",
        "title": "이번 주에 문서화가 필요한 이슈를 모아봅시다",
        "summary": "흩어진 질문과 답변을 한 번에 정리하기 위한 스레드입니다. 커뮤니티와 위키의 연결 지점을 찾는 용도입니다.",
        "tags": ["질문", "정리", "협업"],
        "comment_count": "8",
        "url": "/community/",
    },
    {
        "author": "운영자",
        "created_at": "1시간 전",
        "title": "검색 첫 화면에서 필요한 정보 구조 의견 받습니다",
        "summary": "사용자가 무엇을 먼저 보게 해야 하는지, 최신 문서와 커뮤니티 글의 비중은 어느 정도가 적절한지 논의합니다.",
        "tags": ["검색", "UX", "피드백"],
        "comment_count": "14",
        "url": "/community/",
    },
]


def public_main(request):
    featured_posts = list(_community_visible_posts_queryset(user=None)[:1])
    return render(
        request,
        "pages/home/public_main.html",
        {
            "list_tags": LIST_TAGS,
            "featured_wiki": FEATURED_WIKI[0],
            "featured_post": featured_posts[0] if featured_posts else FEATURED_POSTS[0],
        },
    )


@login_required
def dashboard(request):
    recent_posts = list(
        _community_visible_posts_queryset(user=request.current_user)[:2]
    )
    return render(
        request,
        "pages/home/dashboard.html",
        {
            "page_heading": "Dashboard",
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
            "post_items": recent_posts or FEATURED_POSTS,
        },
    )


@login_required
def community_list(request):
    selected_tag_slug = request.GET.get("tag", "").strip()
    page_number = request.GET.get("page", "1").strip() or "1"
    source_wiki_slug = request.GET.get("wiki_slug", "").strip()
    compose_requested = request.GET.get("compose") == "1" or request.method == "POST"
    prefilled_wiki_document = None
    initial_form_data = None
    wiki_document_queryset = _community_wiki_document_queryset()
    if request.method == "GET" and source_wiki_slug:
        prefilled_wiki_document = wiki_document_queryset.filter(
            slug=source_wiki_slug
        ).first()
        if prefilled_wiki_document is not None:
            initial_form_data = {
                "wiki_documents": [prefilled_wiki_document.pk],
            }

    post_form = PostForm(
        request.POST or None,
        initial=initial_form_data,
        wiki_document_queryset=wiki_document_queryset,
    )
    if request.method == "POST" and post_form.is_valid():
        post = post_form.save(author_user=request.current_user)
        messages.success(request, "게시글을 저장했습니다.")
        return redirect(post.get_absolute_url())

    post_page = _paginate_community_posts(
        _community_visible_posts_queryset(
            user=request.current_user,
            selected_tag_slug=selected_tag_slug,
        ),
        page_number=page_number,
    )
    post_items = list(post_page.object_list)
    _attach_linked_wiki_documents(post_items)
    hot_posts = list(_community_hot_posts_queryset()[:5])
    _attach_linked_wiki_documents(hot_posts)
    next_feed_page_url = (
        _build_community_feed_url(
            page=post_page.next_page_number(),
            selected_tag_slug=selected_tag_slug,
        )
        if post_page.has_next()
        else ""
    )

    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/community_feed_page.html",
            {
                "page_obj": post_page,
                "post_items": post_items,
                "next_feed_page_url": next_feed_page_url,
                "list_tags": LIST_TAGS,
            },
        )

    featured_wiki_documents = list(wiki_document_queryset[:6])
    if prefilled_wiki_document is not None and all(
        document.pk != prefilled_wiki_document.pk
        for document in featured_wiki_documents
    ):
        featured_wiki_documents = [
            prefilled_wiki_document,
            *featured_wiki_documents[:5],
        ]

    return render(
        request,
        "pages/community/list.html",
        {
            "page_heading": "Community",
            "list_tags": LIST_TAGS,
            "post_form": post_form,
            "page_obj": post_page,
            "post_items": post_items,
            "next_feed_page_url": next_feed_page_url,
            "hot_posts": hot_posts,
            "tag_options": list(_community_tag_queryset()[:12]),
            "selected_tag_slug": selected_tag_slug,
            "compose_requested": compose_requested,
            "prefilled_wiki_document": prefilled_wiki_document,
            "featured_wiki_documents": featured_wiki_documents,
            "selected_wiki_document_ids": [
                str(document_id)
                for document_id in (post_form["wiki_documents"].value() or [])
            ],
            "compose_open_url": _build_community_list_url(
                compose=True,
                selected_tag_slug=selected_tag_slug,
                source_wiki_slug=source_wiki_slug,
            ),
            "compose_close_url": _build_community_list_url(
                compose=False,
                selected_tag_slug=selected_tag_slug,
            ),
        },
    )


@login_required
def community_detail(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    comment_form = CommentForm(initial={"parent_comment_id": ""})
    return render(
        request,
        "pages/community/detail.html",
        _build_community_detail_context(
            post=post,
            comment_form=comment_form,
        ),
    )


@login_required
@require_POST
def community_comment_create(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    comment_form = CommentForm(request.POST)
    parent_comment = None
    parent_comment_id = request.POST.get("parent_comment_id", "").strip()
    if parent_comment_id:
        parent_comment = get_object_or_404(
            Comment.objects.filter(
                post=post,
                status=CommentStatus.PUBLISHED,
            ),
            pk=parent_comment_id,
        )
    if comment_form.is_valid():
        comment_form.save(
            post=post,
            author_user=request.current_user,
            parent_comment=parent_comment,
        )
        messages.success(request, "댓글을 등록했습니다.")
        return redirect(f"{post.get_absolute_url()}#comment-list")

    return render(
        request,
        "pages/community/detail.html",
        _build_community_detail_context(
            post=post,
            comment_form=comment_form,
            reply_target_id=parent_comment_id,
        ),
        status=200,
    )


@login_required
def community_comment_children(request, post_id, comment_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    parent_comment = get_object_or_404(
        Comment.objects.filter(post=post, status=CommentStatus.PUBLISHED),
        pk=comment_id,
    )
    return render(
        request,
        "partials/community_comment_children.html",
        {
            "post": post,
            "comments": _get_child_comments(parent_comment),
            "comment_form": CommentForm(),
            "reply_target_id": "",
            "expanded_comment_ids": set(),
            "loaded_parent_comment_id": str(parent_comment.pk),
        },
    )


def wiki_home(request):
    query = request.GET.get("q", "").strip()
    search_results = get_wiki_search_results(query=query, limit=8)
    context = {
        "page_heading": "Wiki",
        "list_tags": LIST_TAGS,
        "query": query,
        "wiki_items": search_results["items"],
        "wiki_result_count": search_results["total_count"],
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/wiki_search_results.html", context)

    return render(
        request,
        "pages/wiki/search_home.html",
        context,
    )


def wiki_detail(request, slug):
    document = get_object_or_404(
        WikiDocument.objects.select_related("current_revision").filter(
            current_revision__isnull=False
        ),
        slug=slug,
        status=WikiDocumentStatus.PUBLISHED,
    )
    revision = document.current_revision
    rendered_revision = get_cached_revision_render(
        revision=revision, title=document.title
    )
    share_url = request.build_absolute_uri(
        reverse("wiki_detail", kwargs={"slug": document.slug})
    )
    return render(
        request,
        "pages/wiki/detail.html",
        {
            "page_heading": document.title,
            "document": document,
            "revision": revision,
            "query": "",
            "display_markdown": rendered_revision["display_markdown"],
            "rendered_markdown": rendered_revision["rendered_markdown"],
            "toc_items": rendered_revision["toc_items"],
            "share_url": share_url,
            "copy_human_text": _build_human_copy(document, revision, share_url),
            "copy_agent_text": _build_agent_copy(document, revision, share_url),
            "compose_post_url": _build_community_compose_url(document),
        },
    )


def integrated_search(request):
    query = request.GET.get("q", "").strip()
    is_htmx_request = request.headers.get("HX-Request") == "true"
    search_results = get_wiki_search_results(query=query, limit=16)
    template_name = (
        "partials/global_search_results.html"
        if is_htmx_request
        else "pages/search/results.html"
    )
    return render(
        request,
        template_name,
        {
            "page_heading": "Search",
            "query": query,
            "list_tags": LIST_TAGS,
            "wiki_items": search_results["items"],
            "wiki_result_count": search_results["total_count"],
            "show_blank_query_state": is_htmx_request and not query,
        },
    )


def _build_human_copy(document, revision, share_url):
    body = (
        strip_leading_title_heading(revision.content_markdown, document.title).strip()
        if revision
        else ""
    )
    parts = [
        document.title,
        "",
        document.summary.strip(),
        "",
        f"링크: {share_url}",
    ]
    if body:
        parts.extend(["", body])
    return "\n".join(parts).strip()


def _build_agent_copy(document, revision, share_url):
    body = (
        strip_leading_title_heading(revision.content_markdown, document.title).strip()
        if revision
        else ""
    )
    lines = [
        "wiki_context:",
        f"  title: {document.title}",
        f"  url: {share_url}",
        "  summary: |",
        *[f"    {line}" for line in document.summary.strip().splitlines()],
    ]
    if body:
        lines.extend(
            [
                "content_markdown: |",
                *[f"  {line}" for line in body.splitlines()],
            ]
        )
    return "\n".join(lines).strip()


def _community_visible_posts_queryset(*, user, selected_tag_slug=""):
    visible_filter = Q(status=PostStatus.PUBLISHED)
    if user is not None:
        visible_filter |= Q(author_user=user, status=PostStatus.DRAFT)

    queryset = (
        Post.objects.filter(visible_filter)
        .select_related("author_user")
        .prefetch_related("tags", "wiki_documents")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__status=CommentStatus.PUBLISHED),
                distinct=True,
            )
        )
        .order_by("-created_at", "-id")
    )
    if selected_tag_slug:
        queryset = queryset.filter(tags__slug=selected_tag_slug)
    return queryset.distinct()


def _community_hot_posts_queryset():
    return (
        Post.objects.filter(status=PostStatus.PUBLISHED)
        .select_related("author_user")
        .prefetch_related("tags", "wiki_documents")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__status=CommentStatus.PUBLISHED),
                distinct=True,
            )
        )
        .order_by("-comment_count", "-created_at", "-id")
    )


def _community_tag_queryset():
    return (
        Tag.objects.filter(posts__status=PostStatus.PUBLISHED)
        .annotate(
            published_post_count=Count(
                "posts", filter=Q(posts__status=PostStatus.PUBLISHED)
            )
        )
        .order_by("-published_post_count", "name")
    )


def _community_wiki_document_queryset():
    return WikiDocument.objects.filter(
        status=WikiDocumentStatus.PUBLISHED,
        current_revision__isnull=False,
    ).order_by("-updated_at", "title")


def _build_community_detail_context(*, post, comment_form, reply_target_id=""):
    expanded_comment_ids = set()
    if reply_target_id:
        comments = _get_comment_tree(post)
        expanded_comment_ids = _get_comment_ancestor_ids(post, reply_target_id)
    else:
        comments = _get_top_level_comments(post)
    linked_wiki_documents = _get_wiki_documents_for_post(post)
    related_posts = list(
        _community_hot_posts_queryset().exclude(pk=post.pk).filter(~Q(pk=post.pk))[:4]
    )
    _attach_linked_wiki_documents(related_posts)
    comment_total_count = Comment.objects.filter(
        post=post,
        status=CommentStatus.PUBLISHED,
    ).count()
    return {
        "page_heading": "Community",
        "post": post,
        "comment_form": comment_form,
        "comments": comments,
        "comment_total_count": comment_total_count,
        "reply_target_id": reply_target_id,
        "expanded_comment_ids": expanded_comment_ids,
        "is_draft": post.status == PostStatus.DRAFT,
        "linked_wiki_documents": linked_wiki_documents,
        "related_posts": related_posts,
    }


def _get_top_level_comments(post):
    return list(
        _comment_queryset()
        .filter(
            post=post,
            parent_comment__isnull=True,
            status=CommentStatus.PUBLISHED,
        )
        .order_by("created_at")
    )


def _get_comment_tree(post):
    comments = list(
        _comment_queryset()
        .filter(
            post=post,
            status=CommentStatus.PUBLISHED,
        )
        .order_by("created_at")
    )
    comments_by_parent_id: dict[str, list[Comment]] = {}
    root_comments: list[Comment] = []
    for comment in comments:
        comment.child_comments = []
        if comment.parent_comment_id is None:
            root_comments.append(comment)
            continue
        comments_by_parent_id.setdefault(str(comment.parent_comment_id), []).append(
            comment
        )

    for comment in comments:
        comment.child_comments = comments_by_parent_id.get(str(comment.pk), [])
    return root_comments


def _get_child_comments(parent_comment):
    return list(
        _comment_queryset()
        .filter(
            parent_comment=parent_comment,
            status=CommentStatus.PUBLISHED,
        )
        .order_by("created_at")
    )


def _comment_queryset():
    return Comment.objects.select_related("author_user").annotate(
        child_comment_count=Count(
            "replies",
            filter=Q(replies__status=CommentStatus.PUBLISHED),
            distinct=True,
        )
    )


def _paginate_community_posts(queryset, *, page_number):
    paginator = Paginator(queryset, COMMUNITY_FEED_PAGE_SIZE)
    return paginator.get_page(page_number)


def _get_comment_ancestor_ids(post, comment_id):
    comments = Comment.objects.filter(
        post=post,
        status=CommentStatus.PUBLISHED,
    ).values("id", "parent_comment_id")
    parent_by_id = {
        str(comment["id"]): (
            str(comment["parent_comment_id"]) if comment["parent_comment_id"] else None
        )
        for comment in comments
    }
    expanded_comment_ids: set[str] = set()
    current_id = comment_id
    while current_id:
        expanded_comment_ids.add(current_id)
        current_id = parent_by_id.get(current_id)
    return expanded_comment_ids


def _get_wiki_documents_for_post(post):
    linked_documents: list[WikiDocument] = []
    seen_document_ids: set[str] = set()

    explicit_documents = list(post.wiki_documents.all())
    for document in explicit_documents:
        document_id = str(document.pk)
        if document_id in seen_document_ids:
            continue
        linked_documents.append(document)
        seen_document_ids.add(document_id)

    wiki_slugs = extract_linked_wiki_slugs(post.content_markdown)
    if not wiki_slugs:
        return linked_documents

    documents_by_slug = {
        document.slug: document
        for document in WikiDocument.objects.filter(
            slug__in=wiki_slugs,
            status=WikiDocumentStatus.PUBLISHED,
            current_revision__isnull=False,
        ).select_related("current_revision")
    }
    for slug in wiki_slugs:
        document = documents_by_slug.get(slug)
        if document is None:
            continue
        document_id = str(document.pk)
        if document_id in seen_document_ids:
            continue
        linked_documents.append(document)
        seen_document_ids.add(document_id)
    return linked_documents


def _attach_linked_wiki_documents(posts):
    posts = list(posts)
    explicit_documents_by_post_id: dict[str, list[WikiDocument]] = {}
    seen_document_ids_by_post_id: dict[str, set[str]] = {}
    slugs: list[str] = []
    for post in posts:
        post_id = str(post.pk)
        explicit_documents = list(post.wiki_documents.all())
        explicit_documents_by_post_id[post_id] = explicit_documents
        seen_document_ids_by_post_id[post_id] = {
            str(document.pk) for document in explicit_documents
        }
        slugs.extend(extract_linked_wiki_slugs(post.content_markdown))

    if not slugs:
        for post in posts:
            post.linked_wiki_documents = explicit_documents_by_post_id[str(post.pk)]
        return

    documents_by_slug = {
        document.slug: document
        for document in WikiDocument.objects.filter(
            slug__in=slugs,
            status=WikiDocumentStatus.PUBLISHED,
            current_revision__isnull=False,
        )
    }
    for post in posts:
        post_id = str(post.pk)
        linked_documents = list(explicit_documents_by_post_id[post_id])
        seen_document_ids = seen_document_ids_by_post_id[post_id]
        for slug in extract_linked_wiki_slugs(post.content_markdown):
            document = documents_by_slug.get(slug)
            if document is None:
                continue
            document_id = str(document.pk)
            if document_id in seen_document_ids:
                continue
            linked_documents.append(document)
            seen_document_ids.add(document_id)
        post.linked_wiki_documents = linked_documents


def _build_community_compose_url(document):
    return f"{reverse('community_list')}?{urlencode({'compose': 1, 'wiki_slug': document.slug})}"


def _build_community_feed_url(*, page, selected_tag_slug=""):
    params = {"page": page}
    if selected_tag_slug:
        params["tag"] = selected_tag_slug
    return f"{reverse('community_list')}?{urlencode(params)}"


def _build_community_list_url(*, compose, selected_tag_slug="", source_wiki_slug=""):
    params = {}
    if selected_tag_slug:
        params["tag"] = selected_tag_slug
    if compose:
        params["compose"] = 1
        if source_wiki_slug:
            params["wiki_slug"] = source_wiki_slug

    base_url = reverse("community_list")
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@login_required
@admin_required
def admin_console(request):
    return render(
        request,
        "pages/admin/dashboard.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "Admin Dashboard",
            "admin_section": "dashboard",
        },
    )


@login_required
@admin_required
def admin_user_management(request):
    all_users = list(
        HiveUser.objects.prefetch_related(
            Prefetch(
                "oauth_accounts",
                queryset=OAuthAccount.objects.order_by("-last_login_at", "provider"),
            )
        ).order_by("-created_at")
    )
    users = [user for user in all_users if user.status != UserStatus.DELETED]
    deleted_users = [user for user in all_users if user.status == UserStatus.DELETED]
    return render(
        request,
        "pages/admin/users.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "User Management",
            "admin_section": "users",
            "users": users,
            "deleted_users": deleted_users,
            "admin_user_count": sum(1 for user in users if user.role == UserRole.ADMIN),
            "active_user_count": sum(
                1 for user in users if user.status == UserStatus.ACTIVE
            ),
            "oauth_connected_user_count": sum(
                1 for user in users if user.oauth_accounts.all()
            ),
            "suspended_user_count": sum(
                1 for user in users if user.status == UserStatus.SUSPENDED
            ),
            "deleted_user_count": len(deleted_users),
        },
    )


@login_required
@admin_required
@require_POST
def admin_user_action(request, user_id):
    target_user = get_object_or_404(HiveUser, pk=user_id)
    action = request.POST.get("action", "").strip()

    try:
        if action not in ADMIN_USER_ACTIONS:
            raise ValueError("지원하지 않는 사용자 액션입니다.")
        message = _apply_admin_user_action(
            actor=request.current_user,
            target_user=target_user,
            action=action,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, message)

    return redirect("admin_user_management")


@login_required
@admin_required
def admin_tag_management(request):
    if request.method == "POST":
        tag_form = TagForm(request.POST)
        if tag_form.is_valid():
            saved_tag = tag_form.save()
            messages.success(request, f"태그 '{saved_tag.name}'를 저장했습니다.")
            return redirect(request.path)
    else:
        tag_form = TagForm()

    return render(
        request,
        "pages/admin/tags.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "Tag Management",
            "admin_section": "tags",
            "tag_form": tag_form,
            "tags": list(Tag.objects.all()),
            "system_tag_count": Tag.objects.filter(tag_type="system").count(),
            "user_tag_count": Tag.objects.filter(tag_type="user").count(),
        },
    )


@login_required
@admin_required
def admin_ingestion_management(request):
    if request.method == "POST":
        source_form = SourceForm(request.POST)
        if source_form.is_valid():
            saved_source = source_form.save(commit=False)
            saved_source.updated_at = timezone.now()
            saved_source.save()
            messages.success(request, f"소스 '{saved_source.name}'를 저장했습니다.")
            return redirect(request.path)
    else:
        source_form = SourceForm()

    source_queryset = Source.objects.annotate(
        document_count=Count("documents", distinct=True),
        pending_document_count=Count(
            "documents",
            filter=Q(documents__fetch_status="PENDING"),
            distinct=True,
        ),
        failed_document_count=Count(
            "documents",
            filter=Q(documents__fetch_status="FAILED"),
            distinct=True,
        ),
        queued_job_count=Count(
            "documents__ingestion_jobs",
            filter=Q(documents__ingestion_jobs__status="QUEUED"),
            distinct=True,
        ),
        failed_job_count=Count(
            "documents__ingestion_jobs",
            filter=Q(documents__ingestion_jobs__status="FAILED"),
            distinct=True,
        ),
    ).order_by("name")
    recent_documents = list(
        SourceDocument.objects.select_related("source").order_by("-collected_at")[:8]
    )
    recent_jobs = list(
        IngestionJob.objects.select_related(
            "source_document", "source_document__source"
        ).order_by("-queued_at")[:8]
    )
    sources = list(source_queryset)
    healthy_source_count = 0
    paused_source_count = 0
    warning_source_count = 0
    failing_source_count = 0
    for source in sources:
        health = _classify_source_health(source)
        source.health_status = health["status"]
        source.health_label = health["label"]
        source.health_badge_class = health["badge_class"]
        source.health_panel_class = health["panel_class"]
        if source.health_status == "healthy":
            healthy_source_count += 1
        elif source.health_status == "paused":
            paused_source_count += 1
        elif source.health_status == "warning":
            warning_source_count += 1
        else:
            failing_source_count += 1

    return render(
        request,
        "pages/admin/ingestion.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "Ingestion Management",
            "admin_section": "ingestion",
            "source_form": source_form,
            "sources": sources,
            "recent_documents": recent_documents,
            "recent_jobs": recent_jobs,
            "document_count": SourceDocument.objects.count(),
            "queued_job_count": IngestionJob.objects.filter(status="QUEUED").count(),
            "failed_job_count": IngestionJob.objects.filter(status="FAILED").count(),
            "healthy_source_count": healthy_source_count,
            "paused_source_count": paused_source_count,
            "warning_source_count": warning_source_count,
            "failing_source_count": failing_source_count,
        },
    )


@login_required
@admin_required
def admin_content_management(request):
    return render(
        request,
        "pages/admin/content.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "Content Management",
            "admin_section": "content",
        },
    )


@login_required
@admin_required
def admin_tag_edit_modal(request, tag_id):
    tag = get_object_or_404(Tag, pk=tag_id)
    form = TagForm(request.POST or None, instance=tag)
    if request.method == "POST" and form.is_valid():
        saved_tag = form.save()
        messages.success(request, f"태그 '{saved_tag.name}'를 저장했습니다.")
        return _htmx_refresh_response()
    return render(
        request,
        "partials/admin/tag_edit_modal.html",
        {
            "tag": tag,
            "tag_form": form,
        },
    )


@login_required
@admin_required
def admin_source_edit_modal(request, source_id):
    source = get_object_or_404(Source, pk=source_id)
    form = SourceForm(request.POST or None, instance=source)
    if request.method == "POST" and form.is_valid():
        saved_source = form.save(commit=False)
        saved_source.updated_at = timezone.now()
        saved_source.save()
        messages.success(request, f"소스 '{saved_source.name}'를 저장했습니다.")
        return _htmx_refresh_response()
    return render(
        request,
        "partials/admin/source_edit_modal.html",
        {
            "source": source,
            "source_form": form,
        },
    )


def _build_admin_summary_context():
    source_counts = Source.objects.aggregate(
        source_count=Count("id"),
        enabled_source_count=Count("id", filter=Q(enabled=True)),
        failing_source_count=Count("id", filter=Q(consecutive_failures__gt=0)),
    )
    return {
        "tag_count": Tag.objects.count(),
        "source_count": source_counts["source_count"],
        "user_count": HiveUser.objects.count(),
        "enabled_source_count": source_counts["enabled_source_count"],
        "failing_source_count": source_counts["failing_source_count"],
        "document_count": SourceDocument.objects.count(),
        "job_count": IngestionJob.objects.count(),
        "search_target": "#admin-search-results",
    }


def _htmx_refresh_response():
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _classify_source_health(source):
    if not source.enabled:
        return {
            "status": "paused",
            "label": "Paused",
            "badge_class": "bg-stone-200 text-stone-700",
            "panel_class": "ring-1 ring-stone-200",
        }
    if (
        source.consecutive_failures > 0
        or source.failed_document_count > 0
        or source.failed_job_count > 0
        or source.last_error_message
    ):
        return {
            "status": "failing",
            "label": "Failing",
            "badge_class": "bg-error-container text-on-error-container",
            "panel_class": "ring-1 ring-red-200",
        }
    if source.pending_document_count > 0 or source.queued_job_count > 0:
        return {
            "status": "warning",
            "label": "Warning",
            "badge_class": "bg-primary-container text-on-primary-container",
            "panel_class": "ring-1 ring-amber-200",
        }
    return {
        "status": "healthy",
        "label": "Healthy",
        "badge_class": "bg-emerald-100 text-emerald-800",
        "panel_class": "ring-1 ring-emerald-200",
    }


def _apply_admin_user_action(*, actor, target_user, action: str) -> str:
    if action not in ADMIN_USER_ACTIONS:
        raise ValueError("지원하지 않는 사용자 액션입니다.")

    if actor.id == target_user.id and action in {"demote_admin", "suspend", "delete"}:
        raise ValueError(
            "자기 자신의 관리자 권한 제거, 비활성화, 삭제는 할 수 없습니다."
        )

    if action == "promote_admin":
        if target_user.role == UserRole.ADMIN:
            raise ValueError("이미 관리자 권한을 가진 사용자입니다.")
        target_user.role = UserRole.ADMIN
        target_user.save(update_fields=["role", "updated_at"])
        return f"{target_user.username} 사용자를 관리자로 승격했습니다."

    if action == "demote_admin":
        if target_user.role != UserRole.ADMIN:
            raise ValueError("관리자 권한을 가진 사용자가 아닙니다.")
        target_user.role = UserRole.USER
        target_user.save(update_fields=["role", "updated_at"])
        return f"{target_user.username} 사용자의 관리자 권한을 해제했습니다."

    if action == "suspend":
        if target_user.status == UserStatus.SUSPENDED:
            raise ValueError("이미 비활성화된 사용자입니다.")
        if target_user.status == UserStatus.DELETED:
            raise ValueError("삭제된 사용자는 먼저 복구할 수 없습니다.")
        target_user.status = UserStatus.SUSPENDED
        target_user.save(update_fields=["status", "updated_at"])
        purge_user_sessions(user=target_user)
        return f"{target_user.username} 사용자를 비활성화했습니다."

    if action == "activate":
        if target_user.status == UserStatus.ACTIVE:
            raise ValueError("이미 활성 사용자입니다.")
        if target_user.status == UserStatus.DELETED:
            raise ValueError("제거된 사용자는 다시 활성화할 수 없습니다.")
        target_user.status = UserStatus.ACTIVE
        target_user.save(update_fields=["status", "updated_at"])
        return f"{target_user.username} 사용자를 다시 활성화했습니다."

    if target_user.status == UserStatus.DELETED:
        raise ValueError("이미 제거된 사용자입니다.")
    original_username = target_user.username
    original_email = target_user.email
    deleted_user_id = target_user.id
    with transaction.atomic():
        target_user.status = UserStatus.DELETED
        target_user.role = UserRole.USER
        target_user.password_hash = None
        target_user.profile_image = None
        target_user.username = _deleted_username_value(target_user)
        target_user.email = _deleted_email_value(target_user)
        target_user.save(
            update_fields=[
                "status",
                "role",
                "password_hash",
                "profile_image",
                "username",
                "email",
                "updated_at",
            ]
        )
        target_user.oauth_accounts.all().delete()
        purge_user_sessions(user=target_user)
    logger.info(
        "user_deleted actor_id=%s target_user_id=%s previous_username=%s previous_email=%s",
        actor.id,
        deleted_user_id,
        original_username,
        original_email,
    )
    return f"{original_username} 사용자를 제거했습니다."


def _deleted_username_value(user) -> str:
    return f"deleted_{str(user.id).replace('-', '')[:8]}"


def _deleted_email_value(user) -> str:
    return f"deleted+{str(user.id).replace('-', '')[:12]}@deleted.local"
