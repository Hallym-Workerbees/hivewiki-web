import logging
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import admin_required, login_required
from apps.accounts.models import HiveUser, OAuthAccount, UserRole, UserStatus
from apps.accounts.notifications import (
    notify_comment_created,
    notify_comment_liked,
    notify_post_liked,
)
from apps.accounts.services import purge_user_sessions

from .community_content import extract_linked_wiki_slugs
from .forms import CommentForm, PostForm, SourceForm, TagForm
from .markdown_rendering import get_cached_revision_render
from .models import (
    Comment,
    CommentLike,
    IngestionJob,
    IngestionJobStatus,
    Post,
    PostBookmark,
    PostLike,
    PostStatus,
    Source,
    SourceDocument,
    SourceDocumentFetchStatus,
    SourceDocumentWikiStatus,
    Tag,
    WikiBookmark,
    WikiDocument,
    WikiDocumentStatus,
)
from .search import get_post_search_results, get_wiki_search_results
from .wiki_markdown import strip_leading_title_heading

logger = logging.getLogger(__name__)
COMMUNITY_FEED_PAGE_SIZE = 10
ADMIN_CONTENT_POST_PAGE_SIZE = 6
ADMIN_CONTENT_WIKI_PAGE_SIZE = 6
ADMIN_INGESTION_SOURCE_PAGE_SIZE = 6
ADMIN_INGESTION_DOCUMENT_PAGE_SIZE = 8
ADMIN_INGESTION_JOB_PAGE_SIZE = 8

ADMIN_USER_ACTIONS = frozenset(
    {
        "promote_admin",
        "demote_admin",
        "suspend",
        "activate",
        "delete",
    }
)
ADMIN_POST_ACTIONS = frozenset({"delete", "restore"})
ADMIN_WIKI_ACTIONS = frozenset({"publish", "archive", "delete"})

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


def community_list(request):
    if request.method == "POST" and request.current_user is None:
        return redirect(_build_login_url(request.get_full_path()))
    selected_tag_slug = request.GET.get("tag", "").strip()
    page_number = request.GET.get("page", "1").strip() or "1"
    source_wiki_slug = request.GET.get("wiki_slug", "").strip()
    selected_draft_post_id = request.GET.get("draft", "").strip()
    compose_requested = request.GET.get("compose") == "1" or request.method == "POST"
    prefilled_wiki_document = None
    initial_form_data = None
    wiki_document_queryset = _community_wiki_document_queryset()
    selected_draft_post = _get_user_draft_post(
        request.current_user,
        selected_draft_post_id or request.POST.get("draft_id", "").strip(),
    )
    if compose_requested and request.current_user is None:
        return redirect(_build_login_url(request.get_full_path()))
    if request.method == "GET":
        if source_wiki_slug:
            prefilled_wiki_document = wiki_document_queryset.filter(
                slug=source_wiki_slug
            ).first()
        if selected_draft_post is not None:
            initial_form_data = _build_post_form_initial_from_post(selected_draft_post)
        if prefilled_wiki_document is not None:
            initial_form_data = _merge_prefilled_wiki_document(
                initial_form_data,
                prefilled_wiki_document,
            )

    post_form = PostForm(
        request.POST or None,
        initial=initial_form_data,
        wiki_document_queryset=wiki_document_queryset,
    )
    if request.method == "POST" and post_form.is_valid():
        draft_post = _get_user_draft_post(
            request.current_user,
            post_form.cleaned_data.get("draft_id"),
        )
        post = post_form.save(author_user=request.current_user, instance=draft_post)
        messages.success(request, "게시글을 저장했습니다.")
        return redirect(post.get_absolute_url())

    post_page = _paginate_community_posts(
        _community_visible_posts_queryset(
            user=request.current_user,
            include_own_drafts=False,
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
    selected_wiki_document_ids = [
        str(document_id) for document_id in (post_form["wiki_documents"].value() or [])
    ]
    selected_wiki_documents = _get_selected_wiki_documents(
        post_form["wiki_documents"].value() or []
    )
    selected_tag_names = _get_selected_tag_names(post_form["tag_names"].value() or "")
    draft_posts = list(_community_user_draft_queryset(request.current_user)[:6])
    for draft_post in draft_posts:
        draft_post.compose_url = _build_community_list_url(
            compose=True,
            selected_tag_slug=selected_tag_slug,
            source_wiki_slug=source_wiki_slug,
            draft_post_id=str(draft_post.pk),
        )
        draft_post.compose_payload = _build_post_form_initial_from_post(draft_post)
        draft_post.compose_payload_script_id = f"community-draft-{draft_post.pk}"

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
            "compose_tag_options": list(_community_tag_queryset()[:40]),
            "selected_tag_names": selected_tag_names,
            "selected_tag_slug": selected_tag_slug,
            "compose_requested": compose_requested,
            "prefilled_wiki_document": prefilled_wiki_document,
            "featured_wiki_documents": featured_wiki_documents,
            "selected_wiki_document_ids": selected_wiki_document_ids,
            "selected_wiki_documents": selected_wiki_documents,
            "locked_wiki_document_ids": (
                [str(prefilled_wiki_document.pk)] if prefilled_wiki_document else []
            ),
            "draft_posts": draft_posts,
            "active_draft_post": selected_draft_post,
            "compose_initial_payload": _build_compose_payload(
                form=post_form,
                selected_wiki_documents=selected_wiki_documents,
                selected_tag_names=selected_tag_names,
            ),
            "compose_wiki_search_url": reverse("community_wiki_picker"),
            "compose_open_url": _build_community_list_url(
                compose=True,
                selected_tag_slug=selected_tag_slug,
                source_wiki_slug=source_wiki_slug,
            )
            if request.current_user
            else _build_login_url(
                _build_community_list_url(
                    compose=True,
                    selected_tag_slug=selected_tag_slug,
                    source_wiki_slug=source_wiki_slug,
                )
            ),
            "compose_close_url": _build_community_list_url(
                compose=False,
                selected_tag_slug=selected_tag_slug,
            ),
        },
    )


def community_detail(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    comment_form = CommentForm(initial={"parent_comment_id": ""})
    focus_comment_id = request.GET.get("comment", "").strip()
    return render(
        request,
        "pages/community/detail.html",
        _build_community_detail_context(
            post=post,
            comment_form=comment_form,
            current_user=request.current_user,
            focus_comment_id=focus_comment_id,
        ),
    )


@login_required
def community_post_edit(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user),
        pk=post_id,
        author_user=request.current_user,
    )
    wiki_document_queryset = _community_wiki_document_queryset()
    post_edit_form = PostForm(
        request.POST or None,
        initial=_build_post_form_initial_from_post(post),
        wiki_document_queryset=wiki_document_queryset,
    )
    if request.method == "POST" and post_edit_form.is_valid():
        post = post_edit_form.save(author_user=request.current_user, instance=post)
        messages.success(request, "게시글을 수정했습니다.")
        return redirect(post.get_absolute_url())

    comment_form = CommentForm(initial={"parent_comment_id": ""})
    return render(
        request,
        "pages/community/detail.html",
        _build_community_detail_context(
            post=post,
            comment_form=comment_form,
            post_edit_form=post_edit_form,
            editing_post=True,
            current_user=request.current_user,
        ),
        status=200,
    )


@login_required
@require_POST
def community_post_like_toggle(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    like = PostLike.objects.filter(post=post, user=request.current_user)
    if like.exists():
        like.delete()
    else:
        PostLike.objects.create(post=post, user=request.current_user)
        notify_post_liked(actor=request.current_user, post=post)
    post.like_count = PostLike.objects.filter(post=post).count()
    post.is_liked_by_current_user = PostLike.objects.filter(
        post=post,
        user=request.current_user,
    ).exists()
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/community_post_like_button.html",
            {
                "post": post,
                "current_user": request.current_user,
                "htmx_enabled": True,
            },
        )
    return redirect(request.POST.get("next") or post.get_absolute_url())


@login_required
@require_POST
def community_post_bookmark_toggle(request, post_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    bookmark = PostBookmark.objects.filter(post=post, user=request.current_user)
    if bookmark.exists():
        bookmark.delete()
    else:
        PostBookmark.objects.create(post=post, user=request.current_user)
    post.is_bookmarked_by_current_user = PostBookmark.objects.filter(
        post=post,
        user=request.current_user,
    ).exists()
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/community_post_bookmark_button.html",
            {
                "post": post,
                "current_user": request.current_user,
                "htmx_enabled": True,
            },
        )
    return redirect(request.POST.get("next") or post.get_absolute_url())


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
                deleted_at__isnull=True,
            ),
            pk=parent_comment_id,
        )
    if comment_form.is_valid():
        comment = comment_form.save(
            post=post,
            author_user=request.current_user,
            parent_comment=parent_comment,
        )
        notify_comment_created(
            actor=request.current_user,
            post=post,
            comment=comment,
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
            current_user=request.current_user,
        ),
        status=200,
    )


@login_required
@require_POST
def community_comment_like_toggle(request, post_id, comment_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    comment = get_object_or_404(
        Comment.objects.filter(post=post, deleted_at__isnull=True),
        pk=comment_id,
    )
    like = CommentLike.objects.filter(comment=comment, user=request.current_user)
    if like.exists():
        like.delete()
    else:
        CommentLike.objects.create(comment=comment, user=request.current_user)
        notify_comment_liked(actor=request.current_user, comment=comment)
    comment.like_count = CommentLike.objects.filter(comment=comment).count()
    comment.is_liked_by_current_user = CommentLike.objects.filter(
        comment=comment,
        user=request.current_user,
    ).exists()
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/community_comment_like_button.html",
            {
                "post": post,
                "comment": comment,
                "current_user": request.current_user,
                "htmx_enabled": True,
            },
        )
    return redirect(
        request.POST.get("next") or f"{post.get_absolute_url()}#comment-{comment.pk}"
    )


@login_required
def community_comment_edit(request, post_id, comment_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    comment = get_object_or_404(
        Comment.objects.filter(
            post=post,
            deleted_at__isnull=True,
            author_user=request.current_user,
        ),
        pk=comment_id,
    )
    comment_edit_form = CommentForm(
        request.POST or None,
        instance=comment,
        initial={"parent_comment_id": comment.parent_comment_id or ""},
    )
    if request.method == "POST" and comment_edit_form.is_valid():
        updated_comment = comment_edit_form.save(
            post=post,
            author_user=request.current_user,
            parent_comment=comment.parent_comment,
            commit=False,
        )
        updated_comment.updated_at = timezone.now()
        updated_comment.save(update_fields=["content", "updated_at"])
        messages.success(request, "댓글을 수정했습니다.")
        return redirect(f"{post.get_absolute_url()}#comment-{comment.pk}")

    return render(
        request,
        "pages/community/detail.html",
        _build_community_detail_context(
            post=post,
            comment_form=CommentForm(initial={"parent_comment_id": ""}),
            editing_comment_id=str(comment.pk),
            comment_edit_form=comment_edit_form,
            current_user=request.current_user,
        ),
        status=200,
    )


def community_comment_children(request, post_id, comment_id):
    post = get_object_or_404(
        _community_visible_posts_queryset(user=request.current_user), pk=post_id
    )
    parent_comment = get_object_or_404(
        Comment.objects.filter(post=post, deleted_at__isnull=True),
        pk=comment_id,
    )
    comments = _get_child_comments(parent_comment)
    _mark_liked_comments(
        comments,
        _get_liked_comment_ids(request.current_user, comments),
    )
    return render(
        request,
        "partials/community_comment_children.html",
        {
            "post": post,
            "comments": comments,
            "comment_form": CommentForm(),
            "reply_target_id": "",
            "expanded_comment_ids": set(),
            "loaded_parent_comment_id": str(parent_comment.pk),
        },
    )


@login_required
def community_wiki_picker(request):
    query = request.GET.get("q", "").strip()
    selected_wiki_document_ids = request.GET.getlist("wiki_documents")
    selected_wiki_documents = _get_selected_wiki_documents(selected_wiki_document_ids)
    selected_id_set = {str(document.pk) for document in selected_wiki_documents}
    locked_id_set = {request.GET.get("locked_wiki_document_id", "").strip()} - {""}
    wiki_results = _community_wiki_document_queryset()
    if query:
        wiki_results = wiki_results.filter(
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(slug__icontains=query)
        )
    wiki_results = list(wiki_results[:8])
    return render(
        request,
        "partials/community_wiki_picker_results.html",
        {
            "wiki_results": wiki_results,
            "selected_wiki_document_ids": selected_id_set,
            "locked_wiki_document_ids": locked_id_set,
            "query": query,
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
    compose_requested = request.GET.get("compose") == "1" or request.method == "POST"
    if compose_requested and request.current_user is None:
        return redirect(_build_login_url(request.get_full_path()))
    selected_draft_post_id = request.GET.get("draft", "").strip()
    wiki_document_queryset = _community_wiki_document_queryset()
    selected_draft_post = _get_user_draft_post(
        request.current_user,
        selected_draft_post_id or request.POST.get("draft_id", "").strip(),
    )
    compose_initial_data = {"wiki_documents": [document.pk]}
    if selected_draft_post is not None:
        compose_initial_data = _build_post_form_initial_from_post(selected_draft_post)
    compose_initial_data = _merge_prefilled_wiki_document(
        compose_initial_data,
        document,
    )
    compose_post_form = PostForm(
        request.POST or None,
        initial=compose_initial_data,
        wiki_document_queryset=wiki_document_queryset,
    )
    if request.method == "POST" and compose_post_form.is_valid():
        draft_post = _get_user_draft_post(
            request.current_user,
            compose_post_form.cleaned_data.get("draft_id"),
        )
        post = compose_post_form.save(
            author_user=request.current_user,
            instance=draft_post,
        )
        messages.success(request, "게시글을 저장했습니다.")
        return redirect(post.get_absolute_url())
    featured_wiki_documents = [document]
    featured_wiki_documents.extend(
        list(wiki_document_queryset.exclude(pk=document.pk)[:5])
    )
    selected_wiki_document_ids = [
        str(document_id)
        for document_id in (compose_post_form["wiki_documents"].value() or [])
    ]
    selected_wiki_documents = _get_selected_wiki_documents(
        compose_post_form["wiki_documents"].value() or []
    )
    selected_tag_names = _get_selected_tag_names(
        compose_post_form["tag_names"].value() or ""
    )
    draft_posts = list(_community_user_draft_queryset(request.current_user)[:6])
    for draft_post in draft_posts:
        draft_post.compose_url = _build_wiki_detail_compose_url(
            document,
            draft_post_id=str(draft_post.pk),
        )
        draft_post.compose_payload = _build_post_form_initial_from_post(draft_post)
        draft_post.compose_payload_script_id = f"community-draft-{draft_post.pk}"
    rendered_revision = get_cached_revision_render(
        revision=revision, title=document.title
    )
    share_url = request.build_absolute_uri(
        reverse("wiki_detail", kwargs={"slug": document.slug})
    )
    document.is_bookmarked_by_current_user = str(
        document.pk
    ) in _get_bookmarked_wiki_ids(
        request.current_user,
        [document],
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
            "compose_open_url": _build_wiki_detail_compose_url(document)
            if request.current_user
            else _build_login_url(_build_wiki_detail_compose_url(document)),
            "compose_close_url": reverse("wiki_detail", kwargs={"slug": document.slug}),
            "compose_submit_url": _build_community_list_url(
                compose=True,
                source_wiki_slug=document.slug,
            ),
            "compose_requested": compose_requested,
            "post_form": compose_post_form,
            "prefilled_wiki_document": document,
            "featured_wiki_documents": featured_wiki_documents,
            "selected_wiki_document_ids": selected_wiki_document_ids,
            "selected_wiki_documents": selected_wiki_documents,
            "locked_wiki_document_ids": [str(document.pk)],
            "compose_wiki_search_url": reverse("community_wiki_picker"),
            "tag_options": list(_community_tag_queryset()[:12]),
            "compose_tag_options": list(_community_tag_queryset()[:40]),
            "selected_tag_names": selected_tag_names,
            "draft_posts": draft_posts,
            "active_draft_post": selected_draft_post,
            "compose_initial_payload": _build_compose_payload(
                form=compose_post_form,
                selected_wiki_documents=selected_wiki_documents,
                selected_tag_names=selected_tag_names,
            ),
        },
    )


@login_required
@require_POST
def wiki_bookmark_toggle(request, slug):
    document = get_object_or_404(
        WikiDocument.objects.filter(
            current_revision__isnull=False,
            status=WikiDocumentStatus.PUBLISHED,
        ),
        slug=slug,
    )
    bookmark = WikiBookmark.objects.filter(
        wiki_document=document,
        user=request.current_user,
    )
    if bookmark.exists():
        bookmark.delete()
    else:
        WikiBookmark.objects.create(
            wiki_document=document,
            user=request.current_user,
        )
    document.is_bookmarked_by_current_user = WikiBookmark.objects.filter(
        wiki_document=document,
        user=request.current_user,
    ).exists()
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/wiki_bookmark_button.html",
            {
                "document": document,
                "current_user": request.current_user,
                "htmx_enabled": True,
            },
        )
    return redirect(
        request.POST.get("next")
        or reverse("wiki_detail", kwargs={"slug": document.slug})
    )


def integrated_search(request):
    query = request.GET.get("q", "").strip()
    is_htmx_request = request.headers.get("HX-Request") == "true"
    wiki_search_results = get_wiki_search_results(query=query, limit=16)
    post_search_results = get_post_search_results(query=query, limit=12)
    _attach_linked_wiki_documents(post_search_results["items"])
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
            "wiki_items": wiki_search_results["items"],
            "wiki_result_count": wiki_search_results["total_count"],
            "post_items": post_search_results["items"],
            "post_result_count": post_search_results["total_count"],
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


def _community_visible_posts_queryset(
    *,
    user,
    selected_tag_slug="",
    include_own_drafts=True,
):
    visible_filter = Q(status=PostStatus.PUBLISHED)
    if include_own_drafts and user is not None:
        visible_filter |= Q(author_user=user, status=PostStatus.DRAFT)

    queryset = (
        Post.objects.filter(visible_filter, deleted_at__isnull=True)
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
    if selected_tag_slug:
        queryset = queryset.filter(tags__slug=selected_tag_slug)
    return queryset.distinct()


def _community_hot_posts_queryset():
    return (
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
        .order_by("-comment_count", "-created_at", "-id")
    )


def _community_related_posts_queryset(post):
    shared_tag_ids = list(post.tags.values_list("pk", flat=True))
    shared_wiki_document_ids = list(post.wiki_documents.values_list("pk", flat=True))
    keyword_candidates = re.findall(
        r"[\w-]{2,}",
        " ".join(
            [
                post.title_cache or "",
                post.summary_cache or "",
                post.body_markdown_cache or "",
            ]
        ),
        flags=re.UNICODE,
    )
    seen_keywords: set[str] = set()
    keywords: list[str] = []
    for keyword in keyword_candidates:
        normalized_keyword = keyword.casefold()
        if normalized_keyword in seen_keywords:
            continue
        seen_keywords.add(normalized_keyword)
        keywords.append(keyword)
        if len(keywords) >= 6:
            break

    queryset = (
        Post.objects.filter(status=PostStatus.PUBLISHED, deleted_at__isnull=True)
        .exclude(pk=post.pk)
        .select_related("author_user")
        .prefetch_related("tags", "wiki_documents")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__deleted_at__isnull=True),
                distinct=True,
            ),
            like_count=Count("post_likes__user", distinct=True),
            shared_tag_count=Count(
                "tags",
                filter=Q(tags__in=shared_tag_ids),
                distinct=True,
            ),
            shared_wiki_document_count=Count(
                "wiki_documents",
                filter=Q(wiki_documents__in=shared_wiki_document_ids),
                distinct=True,
            ),
        )
    )

    if keywords:
        text_match_score = Value(0, output_field=IntegerField())
        for keyword in keywords:
            text_match_score += Case(
                When(
                    Q(title_cache__icontains=keyword)
                    | Q(summary_cache__icontains=keyword)
                    | Q(body_markdown_cache__icontains=keyword),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        queryset = queryset.annotate(text_match_score=text_match_score)
    else:
        queryset = queryset.annotate(
            text_match_score=Value(0, output_field=IntegerField())
        )

    return queryset.filter(
        Q(shared_tag_count__gt=0)
        | Q(shared_wiki_document_count__gt=0)
        | Q(text_match_score__gt=0)
    ).order_by(
        "-shared_wiki_document_count",
        "-shared_tag_count",
        "-text_match_score",
        "-comment_count",
        "-like_count",
        "-created_at",
        "-id",
    )


def _community_tag_queryset():
    return (
        Tag.objects.filter(
            posts__status=PostStatus.PUBLISHED, posts__deleted_at__isnull=True
        )
        .annotate(
            published_post_count=Count(
                "posts",
                filter=Q(
                    posts__status=PostStatus.PUBLISHED,
                    posts__deleted_at__isnull=True,
                ),
            )
        )
        .order_by("-published_post_count", "name")
    )


def _community_wiki_document_queryset():
    return WikiDocument.objects.filter(
        status=WikiDocumentStatus.PUBLISHED,
        current_revision__isnull=False,
    ).order_by("-updated_at", "title")


def _get_selected_wiki_documents(selected_wiki_document_ids):
    selected_ids = [
        str(document_id) for document_id in selected_wiki_document_ids if document_id
    ]
    if not selected_ids:
        return []
    documents_by_id = {
        str(document.pk): document
        for document in _community_wiki_document_queryset().filter(pk__in=selected_ids)
    }
    return [
        documents_by_id[document_id]
        for document_id in selected_ids
        if document_id in documents_by_id
    ]


def _get_selected_tag_names(selected_tag_values):
    if isinstance(selected_tag_values, str):
        raw_values = selected_tag_values.split(",")
    else:
        raw_values = selected_tag_values

    selected_tag_names: list[str] = []
    seen_names: set[str] = set()
    for value in raw_values:
        cleaned_name = " ".join(str(value).strip().split())
        if not cleaned_name:
            continue
        normalized_name = cleaned_name.casefold()
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        selected_tag_names.append(cleaned_name[:50])
    return selected_tag_names


def _build_post_form_initial_from_post(post):
    return {
        "draft_id": str(post.pk),
        "body_markdown": post.body_markdown,
        "tag_names": ", ".join(tag.name for tag in post.tags.order_by("name")),
        "wiki_documents": [str(document.pk) for document in post.wiki_documents.all()],
        "wiki_document_payloads": [
            {
                "id": str(document.pk),
                "title": document.title,
                "summary": document.summary,
            }
            for document in post.wiki_documents.all()
        ],
        "status": post.status,
    }


def _build_compose_payload(*, form, selected_wiki_documents, selected_tag_names):
    return {
        "draft_id": str(form["draft_id"].value() or ""),
        "body_markdown": str(form["body_markdown"].value() or ""),
        "tag_names": ", ".join(selected_tag_names),
        "wiki_document_payloads": [
            {
                "id": str(document.pk),
                "title": document.title,
                "summary": document.summary,
            }
            for document in selected_wiki_documents
        ],
        "status": str(form["status"].value() or PostStatus.PUBLISHED),
    }


def _merge_prefilled_wiki_document(initial_data, wiki_document):
    merged_data = dict(initial_data or {})
    wiki_document_ids = [
        str(document_id)
        for document_id in merged_data.get("wiki_documents", [])
        if document_id
    ]
    prefilled_wiki_document_id = str(wiki_document.pk)
    if prefilled_wiki_document_id not in wiki_document_ids:
        wiki_document_ids.insert(0, prefilled_wiki_document_id)
    merged_data["wiki_documents"] = wiki_document_ids
    return merged_data


def _community_user_draft_queryset(user):
    if user is None:
        return Post.objects.none()
    return (
        Post.objects.filter(
            author_user=user,
            status=PostStatus.DRAFT,
            deleted_at__isnull=True,
        )
        .prefetch_related("tags", "wiki_documents")
        .order_by("-updated_at", "-created_at", "-id")
    )


def _get_user_draft_post(user, draft_post_id):
    if user is None or not draft_post_id:
        return None
    return _community_user_draft_queryset(user).filter(pk=draft_post_id).first()


def _get_liked_post_ids(user, posts):
    if user is None:
        return set()
    post_ids = [post.pk for post in posts]
    if not post_ids:
        return set()
    return {
        str(post_id)
        for post_id in PostLike.objects.filter(
            user=user,
            post_id__in=post_ids,
        ).values_list("post_id", flat=True)
    }


def _get_bookmarked_post_ids(user, posts):
    if user is None:
        return set()
    post_ids = [post.pk for post in posts]
    if not post_ids:
        return set()
    return {
        str(post_id)
        for post_id in PostBookmark.objects.filter(
            user=user,
            post_id__in=post_ids,
        ).values_list("post_id", flat=True)
    }


def _get_bookmarked_wiki_ids(user, documents):
    if user is None:
        return set()
    document_ids = [document.pk for document in documents]
    if not document_ids:
        return set()
    return {
        str(document_id)
        for document_id in WikiBookmark.objects.filter(
            user=user,
            wiki_document_id__in=document_ids,
        ).values_list("wiki_document_id", flat=True)
    }


def _collect_comment_ids(comments):
    comment_ids = []
    for comment in comments:
        comment_ids.append(comment.pk)
        comment_ids.extend(_collect_comment_ids(getattr(comment, "child_comments", [])))
    return comment_ids


def _mark_liked_comments(comments, liked_comment_ids):
    for comment in comments:
        comment.is_liked_by_current_user = str(comment.pk) in liked_comment_ids
        _mark_liked_comments(getattr(comment, "child_comments", []), liked_comment_ids)


def _get_liked_comment_ids(user, comments):
    if user is None:
        return set()
    comment_ids = _collect_comment_ids(comments)
    if not comment_ids:
        return set()
    return {
        str(comment_id)
        for comment_id in CommentLike.objects.filter(
            user=user,
            comment_id__in=comment_ids,
        ).values_list("comment_id", flat=True)
    }


def _build_community_detail_context(
    *,
    post,
    comment_form,
    current_user,
    focus_comment_id="",
    reply_target_id="",
    post_edit_form=None,
    editing_post=False,
    comment_edit_form=None,
    editing_comment_id="",
):
    expanded_comment_ids = set()
    if reply_target_id or editing_comment_id or focus_comment_id:
        comments = _get_comment_tree(post)
        target_comment_id = reply_target_id or editing_comment_id or focus_comment_id
        expanded_comment_ids = _get_comment_ancestor_ids(post, target_comment_id)
    else:
        comments = _get_top_level_comments(post)
    linked_wiki_documents = _get_wiki_documents_for_post(post)
    liked_post_ids = _get_liked_post_ids(current_user, [post])
    bookmarked_post_ids = _get_bookmarked_post_ids(current_user, [post])
    liked_comment_ids = _get_liked_comment_ids(current_user, comments)
    post.is_liked_by_current_user = str(post.pk) in liked_post_ids
    post.is_bookmarked_by_current_user = str(post.pk) in bookmarked_post_ids
    _mark_liked_comments(comments, liked_comment_ids)
    related_posts = list(_community_related_posts_queryset(post)[:4])
    if len(related_posts) < 4:
        fallback_posts = list(
            _community_hot_posts_queryset()
            .exclude(pk=post.pk)
            .exclude(pk__in=[related_post.pk for related_post in related_posts])[
                : 4 - len(related_posts)
            ]
        )
        related_posts.extend(fallback_posts)
    _attach_linked_wiki_documents(related_posts)
    post_edit_form = post_edit_form or PostForm(
        initial=_build_post_form_initial_from_post(post),
        wiki_document_queryset=_community_wiki_document_queryset(),
    )
    selected_wiki_document_ids = [
        str(document_id)
        for document_id in (post_edit_form["wiki_documents"].value() or [])
    ]
    selected_wiki_documents = _get_selected_wiki_documents(
        post_edit_form["wiki_documents"].value() or []
    )
    featured_wiki_documents = list(selected_wiki_documents)
    for document in _community_wiki_document_queryset():
        if any(
            existing_document.pk == document.pk
            for existing_document in featured_wiki_documents
        ):
            continue
        featured_wiki_documents.append(document)
        if len(featured_wiki_documents) >= 6:
            break
    comment_total_count = Comment.objects.filter(
        post=post,
        deleted_at__isnull=True,
    ).count()
    return {
        "page_heading": "Community",
        "post": post,
        "current_user": current_user,
        "comment_form": comment_form,
        "comments": comments,
        "comment_total_count": comment_total_count,
        "reply_target_id": reply_target_id,
        "expanded_comment_ids": expanded_comment_ids,
        "is_draft": post.status == PostStatus.DRAFT,
        "linked_wiki_documents": linked_wiki_documents,
        "related_posts": related_posts,
        "editing_post": editing_post,
        "post_edit_form": post_edit_form,
        "editing_comment_id": editing_comment_id,
        "comment_edit_form": comment_edit_form or CommentForm(instance=Comment()),
        "compose_requested": editing_post,
        "compose_mode": "edit" if editing_post else "create",
        "compose_title_eyebrow": "게시글 수정",
        "compose_heading": "내 게시글 다듬기",
        "compose_description": "본문, 태그, 관련 위키를 수정해 흐름을 다시 정리할 수 있습니다.",
        "compose_submit_label": "수정 저장",
        "post_edit_submit_url": reverse(
            "community_post_edit", kwargs={"post_id": post.pk}
        ),
        "compose_close_url": post.get_absolute_url(),
        "compose_wiki_search_url": reverse("community_wiki_picker"),
        "featured_wiki_documents": featured_wiki_documents,
        "selected_wiki_document_ids": selected_wiki_document_ids,
        "selected_wiki_documents": selected_wiki_documents,
        "locked_wiki_document_ids": [],
        "compose_tag_options": list(_community_tag_queryset()[:40]),
        "selected_tag_names": _get_selected_tag_names(
            post_edit_form["tag_names"].value() or ""
        ),
        "draft_posts": [],
        "active_draft_post": None,
        "compose_initial_payload": _build_compose_payload(
            form=post_edit_form,
            selected_wiki_documents=selected_wiki_documents,
            selected_tag_names=_get_selected_tag_names(
                post_edit_form["tag_names"].value() or ""
            ),
        ),
    }


def _get_top_level_comments(post):
    return list(
        _comment_queryset()
        .filter(
            post=post,
            parent_comment__isnull=True,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
    )


def _get_comment_tree(post):
    comments = list(
        _comment_queryset()
        .filter(
            post=post,
            deleted_at__isnull=True,
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
            deleted_at__isnull=True,
        )
        .order_by("created_at")
    )


def _comment_queryset():
    return Comment.objects.select_related("author_user").annotate(
        like_count=Count("comment_likes__user", distinct=True),
        child_comment_count=Count(
            "replies",
            filter=Q(replies__deleted_at__isnull=True),
            distinct=True,
        ),
    )


def _paginate_community_posts(queryset, *, page_number):
    paginator = Paginator(queryset, COMMUNITY_FEED_PAGE_SIZE)
    return paginator.get_page(page_number)


def _get_comment_ancestor_ids(post, comment_id):
    comments = Comment.objects.filter(
        post=post,
        deleted_at__isnull=True,
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


def _build_login_url(next_path):
    return f"{reverse('login')}?{urlencode({'next': next_path})}"


def _build_wiki_detail_compose_url(document, draft_post_id=""):
    params = {"compose": 1}
    if draft_post_id:
        params["draft"] = draft_post_id
    return (
        f"{reverse('wiki_detail', kwargs={'slug': document.slug})}?{urlencode(params)}"
    )


def _build_community_feed_url(*, page, selected_tag_slug=""):
    params = {"page": page}
    if selected_tag_slug:
        params["tag"] = selected_tag_slug
    return f"{reverse('community_list')}?{urlencode(params)}"


def _build_community_list_url(
    *,
    compose,
    selected_tag_slug="",
    source_wiki_slug="",
    draft_post_id="",
):
    params = {}
    if selected_tag_slug:
        params["tag"] = selected_tag_slug
    if compose:
        params["compose"] = 1
        if source_wiki_slug:
            params["wiki_slug"] = source_wiki_slug
        if draft_post_id:
            params["draft"] = draft_post_id

    base_url = reverse("community_list")
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _build_admin_content_querystring(request, **updates):
    params = request.GET.copy()
    for key, value in updates.items():
        if value in ("", None):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def _build_admin_content_url(request, **updates):
    query = _build_admin_content_querystring(request, **updates)
    if not query:
        return request.path
    return f"{request.path}?{query}"


def _build_admin_ingestion_querystring(request, **updates):
    params = request.GET.copy()
    for key, value in updates.items():
        if value in ("", None):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def _build_admin_ingestion_url(request, **updates):
    query = _build_admin_ingestion_querystring(request, **updates)
    if not query:
        return request.path
    return f"{request.path}?{query}"


@login_required
@admin_required
def admin_console(request):
    context = {
        **_build_admin_summary_context(),
        "page_heading": "Admin Dashboard",
        "admin_section": "dashboard",
        "admin_intro_template": "partials/admin/dashboard_hero.html",
        "admin_content_template": "partials/admin/page_content/dashboard.html",
    }
    return _render_admin_page(
        request,
        "pages/admin/dashboard.html",
        context,
        {
            "summary": "partials/admin/dashboard_summary_stats.html",
            "overview": "partials/admin/dashboard_overview_panel.html",
            "signals": "partials/admin/dashboard_signals_panel.html",
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
    context = {
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
        "admin_content_template": "partials/admin/page_content/users.html",
    }
    return _render_admin_page(
        request,
        "pages/admin/users.html",
        context,
        {
            "summary": "partials/admin/users_summary_stats.html",
            "users_list": "partials/admin/users_active_list.html",
            "deleted_users": "partials/admin/users_deleted_list.html",
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

    context = {
        **_build_admin_summary_context(),
        "page_heading": "Tag Management",
        "admin_section": "tags",
        "tag_form": tag_form,
        "tags": list(Tag.objects.all()),
        "system_tag_count": Tag.objects.filter(tag_type="system").count(),
        "user_tag_count": Tag.objects.filter(tag_type="user").count(),
        "admin_content_template": "partials/admin/page_content/tags.html",
    }
    return _render_admin_page(
        request,
        "pages/admin/tags.html",
        context,
        {
            "summary": "partials/admin/tags_summary_stats.html",
            "tag_form": "partials/admin/tags_create_panel.html",
            "tag_list": "partials/admin/tags_list_panel.html",
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

    source_query = request.GET.get("source_query", "").strip()
    selected_source_health = request.GET.get("source_health", "").strip()
    selected_source_enabled = request.GET.get("source_enabled", "").strip()
    document_query = request.GET.get("document_query", "").strip()
    selected_document_fetch_status = request.GET.get(
        "document_fetch_status", ""
    ).strip()
    selected_document_wiki_status = request.GET.get("document_wiki_status", "").strip()
    job_query = request.GET.get("job_query", "").strip()
    selected_job_status = request.GET.get("job_status", "").strip()

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
    )
    if source_query:
        source_queryset = source_queryset.filter(
            Q(name__icontains=source_query) | Q(target_url__icontains=source_query)
        )
    if selected_source_enabled == "enabled":
        source_queryset = source_queryset.filter(enabled=True)
    elif selected_source_enabled == "disabled":
        source_queryset = source_queryset.filter(enabled=False)
    if selected_source_health == "healthy":
        source_queryset = source_queryset.filter(
            enabled=True,
            consecutive_failures=0,
            failed_document_count=0,
            failed_job_count=0,
            pending_document_count=0,
            queued_job_count=0,
        ).filter(Q(last_error_message__isnull=True) | Q(last_error_message=""))
    elif selected_source_health == "warning":
        source_queryset = source_queryset.filter(
            enabled=True,
            consecutive_failures=0,
            failed_document_count=0,
            failed_job_count=0,
        ).filter(Q(last_error_message__isnull=True) | Q(last_error_message=""))
        source_queryset = source_queryset.filter(
            Q(pending_document_count__gt=0) | Q(queued_job_count__gt=0)
        )
    elif selected_source_health == "failing":
        source_queryset = source_queryset.filter(enabled=True).filter(
            Q(consecutive_failures__gt=0)
            | Q(failed_document_count__gt=0)
            | Q(failed_job_count__gt=0)
            | (Q(last_error_message__isnull=False) & ~Q(last_error_message=""))
        )
    elif selected_source_health == "paused":
        source_queryset = source_queryset.filter(enabled=False)
    source_queryset = source_queryset.order_by("name").distinct()

    recent_documents_queryset = SourceDocument.objects.select_related(
        "source"
    ).order_by("-collected_at")
    if document_query:
        recent_documents_queryset = recent_documents_queryset.filter(
            Q(title__icontains=document_query)
            | Q(canonical_url__icontains=document_query)
            | Q(source__name__icontains=document_query)
        )
    if selected_document_fetch_status in {
        SourceDocumentFetchStatus.PENDING,
        SourceDocumentFetchStatus.FETCHED,
        SourceDocumentFetchStatus.FAILED,
    }:
        recent_documents_queryset = recent_documents_queryset.filter(
            fetch_status=selected_document_fetch_status
        )
    if selected_document_wiki_status in {
        SourceDocumentWikiStatus.NOT_REQUESTED,
        SourceDocumentWikiStatus.REQUESTED,
        SourceDocumentWikiStatus.COMPLETED,
        SourceDocumentWikiStatus.FAILED,
    }:
        recent_documents_queryset = recent_documents_queryset.filter(
            wiki_status=selected_document_wiki_status
        )

    recent_jobs_queryset = IngestionJob.objects.select_related(
        "source_document", "source_document__source"
    ).order_by("-queued_at")
    if job_query:
        recent_jobs_queryset = recent_jobs_queryset.filter(
            Q(source_document__title__icontains=job_query)
            | Q(source_document__canonical_url__icontains=job_query)
            | Q(source_document__source__name__icontains=job_query)
            | Q(error_message__icontains=job_query)
        )
    if selected_job_status in {
        IngestionJobStatus.QUEUED,
        IngestionJobStatus.STARTED,
        IngestionJobStatus.COMPLETED,
        IngestionJobStatus.FAILED,
    }:
        recent_jobs_queryset = recent_jobs_queryset.filter(status=selected_job_status)

    source_paginator = Paginator(source_queryset, ADMIN_INGESTION_SOURCE_PAGE_SIZE)
    source_page_obj = source_paginator.get_page(request.GET.get("source_page") or 1)
    sources = source_page_obj
    document_paginator = Paginator(
        recent_documents_queryset, ADMIN_INGESTION_DOCUMENT_PAGE_SIZE
    )
    recent_documents = document_paginator.get_page(
        request.GET.get("document_page") or 1
    )
    job_paginator = Paginator(recent_jobs_queryset, ADMIN_INGESTION_JOB_PAGE_SIZE)
    recent_jobs = job_paginator.get_page(request.GET.get("job_page") or 1)

    health_count_queryset = Source.objects.annotate(
        pending_document_count=Count(
            "documents",
            filter=Q(documents__fetch_status=SourceDocumentFetchStatus.PENDING),
            distinct=True,
        ),
        failed_document_count=Count(
            "documents",
            filter=Q(documents__fetch_status=SourceDocumentFetchStatus.FAILED),
            distinct=True,
        ),
        queued_job_count=Count(
            "documents__ingestion_jobs",
            filter=Q(documents__ingestion_jobs__status=IngestionJobStatus.QUEUED),
            distinct=True,
        ),
        failed_job_count=Count(
            "documents__ingestion_jobs",
            filter=Q(documents__ingestion_jobs__status=IngestionJobStatus.FAILED),
            distinct=True,
        ),
    )
    healthy_source_count = 0
    paused_source_count = 0
    warning_source_count = 0
    failing_source_count = 0
    for source in health_count_queryset:
        health = _classify_source_health(source)
        if health["status"] == "healthy":
            healthy_source_count += 1
        elif health["status"] == "paused":
            paused_source_count += 1
        elif health["status"] == "warning":
            warning_source_count += 1
        else:
            failing_source_count += 1

    for source in sources:
        health = _classify_source_health(source)
        source.health_status = health["status"]
        source.health_label = health["label"]
        source.health_badge_class = health["badge_class"]
        source.health_panel_class = health["panel_class"]

    context = {
        **_build_admin_summary_context(),
        "page_heading": "Ingestion Management",
        "admin_section": "ingestion",
        "source_form": source_form,
        "sources": sources,
        "recent_documents": recent_documents,
        "recent_jobs": recent_jobs,
        "source_query": source_query,
        "selected_source_health": selected_source_health,
        "selected_source_enabled": selected_source_enabled,
        "document_query": document_query,
        "selected_document_fetch_status": selected_document_fetch_status,
        "selected_document_wiki_status": selected_document_wiki_status,
        "job_query": job_query,
        "selected_job_status": selected_job_status,
        "source_health_choices": [
            ("", "전체 상태"),
            ("healthy", "Healthy"),
            ("warning", "Warning"),
            ("failing", "Failing"),
            ("paused", "Paused"),
        ],
        "source_enabled_choices": [
            ("", "활성/비활성 전체"),
            ("enabled", "활성만"),
            ("disabled", "비활성만"),
        ],
        "document_fetch_status_choices": [
            ("", "fetch 전체"),
            (SourceDocumentFetchStatus.PENDING, "Pending"),
            (SourceDocumentFetchStatus.FETCHED, "Fetched"),
            (SourceDocumentFetchStatus.FAILED, "Failed"),
        ],
        "document_wiki_status_choices": [
            ("", "wiki 전체"),
            (SourceDocumentWikiStatus.NOT_REQUESTED, "Not requested"),
            (SourceDocumentWikiStatus.REQUESTED, "Requested"),
            (SourceDocumentWikiStatus.COMPLETED, "Completed"),
            (SourceDocumentWikiStatus.FAILED, "Failed"),
        ],
        "job_status_choices": [
            ("", "잡 상태 전체"),
            (IngestionJobStatus.QUEUED, "Queued"),
            (IngestionJobStatus.STARTED, "Started"),
            (IngestionJobStatus.COMPLETED, "Completed"),
            (IngestionJobStatus.FAILED, "Failed"),
        ],
        "source_prev_url": (
            _build_admin_ingestion_url(
                request,
                section="sources",
                source_page=source_page_obj.previous_page_number(),
            )
            if source_page_obj.has_previous()
            else ""
        ),
        "source_next_url": (
            _build_admin_ingestion_url(
                request,
                section="sources",
                source_page=source_page_obj.next_page_number(),
            )
            if source_page_obj.has_next()
            else ""
        ),
        "document_prev_url": (
            _build_admin_ingestion_url(
                request,
                section="recent_documents",
                document_page=recent_documents.previous_page_number(),
            )
            if recent_documents.has_previous()
            else ""
        ),
        "document_next_url": (
            _build_admin_ingestion_url(
                request,
                section="recent_documents",
                document_page=recent_documents.next_page_number(),
            )
            if recent_documents.has_next()
            else ""
        ),
        "job_prev_url": (
            _build_admin_ingestion_url(
                request,
                section="recent_jobs",
                job_page=recent_jobs.previous_page_number(),
            )
            if recent_jobs.has_previous()
            else ""
        ),
        "job_next_url": (
            _build_admin_ingestion_url(
                request,
                section="recent_jobs",
                job_page=recent_jobs.next_page_number(),
            )
            if recent_jobs.has_next()
            else ""
        ),
        "sources_refresh_query": _build_admin_ingestion_querystring(
            request, section="sources"
        ),
        "documents_refresh_query": _build_admin_ingestion_querystring(
            request, section="recent_documents"
        ),
        "jobs_refresh_query": _build_admin_ingestion_querystring(
            request, section="recent_jobs"
        ),
        "document_count": SourceDocument.objects.count(),
        "queued_job_count": IngestionJob.objects.filter(
            status=IngestionJobStatus.QUEUED
        ).count(),
        "failed_job_count": IngestionJob.objects.filter(
            status=IngestionJobStatus.FAILED
        ).count(),
        "healthy_source_count": healthy_source_count,
        "paused_source_count": paused_source_count,
        "warning_source_count": warning_source_count,
        "failing_source_count": failing_source_count,
        "admin_content_template": "partials/admin/page_content/ingestion.html",
    }
    return _render_admin_page(
        request,
        "pages/admin/ingestion.html",
        context,
        {
            "summary": "partials/admin/ingestion_summary_stats.html",
            "source_form": "partials/admin/ingestion_create_panel.html",
            "sources": "partials/admin/ingestion_sources_panel.html",
            "recent_documents": "partials/admin/ingestion_documents_panel.html",
            "recent_jobs": "partials/admin/ingestion_jobs_panel.html",
        },
    )


@login_required
@admin_required
def admin_content_management(request):
    post_query = request.GET.get("post_query", "").strip()
    selected_post_tag = request.GET.get("post_tag", "").strip()
    post_visibility = request.GET.get("post_visibility", "active").strip()
    if post_visibility not in {"active", "deleted", "all"}:
        post_visibility = "active"
    wiki_query = request.GET.get("wiki_query", "").strip()
    selected_wiki_status = request.GET.get("wiki_status", "").strip()

    posts_queryset = (
        Post.objects.filter(status=PostStatus.PUBLISHED)
        .select_related("author_user")
        .prefetch_related("tags")
        .annotate(
            comment_count=Count(
                "comments",
                filter=Q(comments__deleted_at__isnull=True),
                distinct=True,
            ),
            linked_wiki_count=Count("wiki_documents", distinct=True),
            visibility_rank=Case(
                When(deleted_at__isnull=True, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by("visibility_rank", "-updated_at", "-id")
    )
    if post_query:
        posts_queryset = posts_queryset.filter(
            Q(title_cache__icontains=post_query)
            | Q(summary_cache__icontains=post_query)
            | Q(body_markdown_cache__icontains=post_query)
            | Q(author_user__username__icontains=post_query)
        )
    if selected_post_tag:
        posts_queryset = posts_queryset.filter(tags__slug=selected_post_tag)
    if post_visibility == "active":
        posts_queryset = posts_queryset.filter(deleted_at__isnull=True)
    elif post_visibility == "deleted":
        posts_queryset = posts_queryset.filter(deleted_at__isnull=False)

    post_filter_tags = list(
        Tag.objects.filter(posts__status=PostStatus.PUBLISHED)
        .annotate(
            admin_post_count=Count(
                "posts",
                filter=Q(posts__status=PostStatus.PUBLISHED),
                distinct=True,
            )
        )
        .order_by("-admin_post_count", "name")
        .distinct()
    )
    post_paginator = Paginator(posts_queryset.distinct(), ADMIN_CONTENT_POST_PAGE_SIZE)
    recent_posts = post_paginator.get_page(request.GET.get("post_page") or 1)

    wiki_queryset = (
        WikiDocument.objects.select_related("current_revision")
        .annotate(
            community_post_count=Count(
                "community_posts",
                filter=Q(community_posts__deleted_at__isnull=True),
                distinct=True,
            ),
            revision_count=Count("revisions", distinct=True),
        )
        .order_by("-updated_at", "title")
    )
    if wiki_query:
        wiki_queryset = wiki_queryset.filter(
            Q(title__icontains=wiki_query)
            | Q(summary__icontains=wiki_query)
            | Q(slug__icontains=wiki_query)
        )
    if selected_wiki_status in {
        WikiDocumentStatus.PUBLISHED,
        WikiDocumentStatus.ARCHIVED,
        WikiDocumentStatus.DELETED,
    }:
        wiki_queryset = wiki_queryset.filter(status=selected_wiki_status)
    wiki_paginator = Paginator(wiki_queryset.distinct(), ADMIN_CONTENT_WIKI_PAGE_SIZE)
    recent_wiki_documents = wiki_paginator.get_page(request.GET.get("wiki_page") or 1)

    context = {
        **_build_admin_summary_context(),
        "page_heading": "Content Management",
        "admin_section": "content",
        "recent_posts": recent_posts,
        "recent_wiki_documents": recent_wiki_documents,
        "post_query": post_query,
        "selected_post_tag": selected_post_tag,
        "post_visibility": post_visibility,
        "post_filter_tags": post_filter_tags,
        "wiki_query": wiki_query,
        "selected_wiki_status": selected_wiki_status,
        "wiki_status_choices": [
            ("", "전체 상태"),
            (WikiDocumentStatus.PUBLISHED, "게시"),
            (WikiDocumentStatus.ARCHIVED, "아카이브"),
            (WikiDocumentStatus.DELETED, "삭제"),
        ],
        "post_prev_url": (
            _build_admin_content_url(
                request,
                section="posts",
                post_page=recent_posts.previous_page_number(),
            )
            if recent_posts.has_previous()
            else ""
        ),
        "post_next_url": (
            _build_admin_content_url(
                request,
                section="posts",
                post_page=recent_posts.next_page_number(),
            )
            if recent_posts.has_next()
            else ""
        ),
        "wiki_prev_url": (
            _build_admin_content_url(
                request,
                section="wiki_documents",
                wiki_page=recent_wiki_documents.previous_page_number(),
            )
            if recent_wiki_documents.has_previous()
            else ""
        ),
        "wiki_next_url": (
            _build_admin_content_url(
                request,
                section="wiki_documents",
                wiki_page=recent_wiki_documents.next_page_number(),
            )
            if recent_wiki_documents.has_next()
            else ""
        ),
        "post_refresh_query": _build_admin_content_querystring(
            request, section="posts"
        ),
        "wiki_refresh_query": _build_admin_content_querystring(
            request,
            section="wiki_documents",
        ),
        "visible_post_count": Post.objects.filter(
            deleted_at__isnull=True,
            status=PostStatus.PUBLISHED,
        ).count(),
        "deleted_post_count": Post.objects.filter(deleted_at__isnull=False).count(),
        "published_wiki_count": WikiDocument.objects.filter(
            status=WikiDocumentStatus.PUBLISHED
        ).count(),
        "archived_wiki_count": WikiDocument.objects.filter(
            status=WikiDocumentStatus.ARCHIVED
        ).count(),
        "deleted_wiki_count": WikiDocument.objects.filter(
            status=WikiDocumentStatus.DELETED
        ).count(),
        "admin_content_template": "partials/admin/page_content/content.html",
    }
    return _render_admin_page(
        request,
        "pages/admin/content.html",
        context,
        {
            "summary": "partials/admin/content_summary_stats.html",
            "posts": "partials/admin/content_posts_panel.html",
            "wiki_documents": "partials/admin/content_wiki_panel.html",
        },
    )


@login_required
@admin_required
@require_POST
def admin_post_action(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    action = request.POST.get("action", "").strip()

    try:
        if action not in ADMIN_POST_ACTIONS:
            raise ValueError("지원하지 않는 게시글 액션입니다.")
        message = _apply_admin_post_action(post=post, action=action)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, message)

    return redirect("admin_content_management")


@login_required
@admin_required
@require_POST
def admin_wiki_action(request, wiki_id):
    wiki_document = get_object_or_404(WikiDocument, pk=wiki_id)
    action = request.POST.get("action", "").strip()

    try:
        if action not in ADMIN_WIKI_ACTIONS:
            raise ValueError("지원하지 않는 위키 액션입니다.")
        message = _apply_admin_wiki_action(wiki_document=wiki_document, action=action)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, message)

    return redirect("admin_content_management")


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
    if request.method == "POST" and request.POST.get("action") == "delete":
        source_name = source.name
        source.delete()
        messages.success(
            request,
            (
                f"소스 '{source_name}'를 삭제했습니다. "
                "연결된 수집 문서와 ingestion job도 함께 제거되었습니다."
            ),
        )
        return _htmx_refresh_response()

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
        "post_count": Post.objects.count(),
        "wiki_document_count": WikiDocument.objects.count(),
        "search_target": "#admin-search-results",
    }


def _htmx_refresh_response():
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def _render_admin_page(request, template_name, context, partial_templates):
    if request.headers.get("HX-Request") == "true":
        section = request.GET.get("section", "").strip()
        partial_template = partial_templates.get(section)
        if partial_template:
            return render(request, partial_template, context)
        return render(request, "partials/admin/page_shell.html", context)
    return render(request, template_name, context)


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


def _apply_admin_post_action(*, post, action: str) -> str:
    post_label = post.title or post.summary or str(post.pk)

    if action == "delete":
        if post.deleted_at is not None:
            raise ValueError("이미 삭제 처리된 게시글입니다.")
        post.deleted_at = timezone.now()
        post.updated_at = timezone.now()
        post.save(update_fields=["deleted_at", "updated_at"])
        return f"게시글 '{post_label}'을 삭제 처리했습니다."

    if post.deleted_at is None:
        raise ValueError("복구할 삭제 게시글이 아닙니다.")
    post.deleted_at = None
    post.updated_at = timezone.now()
    post.save(update_fields=["deleted_at", "updated_at"])
    return f"게시글 '{post_label}'을 복구했습니다."


def _apply_admin_wiki_action(*, wiki_document, action: str) -> str:
    if action == "publish":
        if wiki_document.status == WikiDocumentStatus.PUBLISHED:
            raise ValueError("이미 게시 중인 위키 문서입니다.")
        if wiki_document.current_revision_id is None:
            raise ValueError("현재 리비전이 없는 위키 문서는 게시할 수 없습니다.")
        wiki_document.status = WikiDocumentStatus.PUBLISHED
        wiki_document.updated_at = timezone.now()
        wiki_document.save(update_fields=["status", "updated_at"])
        return f"위키 '{wiki_document.title}'를 게시 상태로 전환했습니다."

    if action == "archive":
        if wiki_document.status == WikiDocumentStatus.ARCHIVED:
            raise ValueError("이미 아카이브된 위키 문서입니다.")
        wiki_document.status = WikiDocumentStatus.ARCHIVED
        wiki_document.updated_at = timezone.now()
        wiki_document.save(update_fields=["status", "updated_at"])
        return f"위키 '{wiki_document.title}'를 아카이브했습니다."

    if wiki_document.status == WikiDocumentStatus.DELETED:
        raise ValueError("이미 삭제된 위키 문서입니다.")
    wiki_document.status = WikiDocumentStatus.DELETED
    wiki_document.updated_at = timezone.now()
    wiki_document.save(update_fields=["status", "updated_at"])
    return f"위키 '{wiki_document.title}'를 삭제 상태로 전환했습니다."


def _deleted_username_value(user) -> str:
    return f"deleted_{str(user.id).replace('-', '')[:8]}"


def _deleted_email_value(user) -> str:
    return f"deleted+{str(user.id).replace('-', '')[:12]}@deleted.local"
