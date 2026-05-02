from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import admin_required, login_required
from apps.accounts.models import HiveUser, OAuthAccount, UserRole, UserStatus

from .forms import SourceForm, TagForm
from .models import IngestionJob, Source, SourceDocument, Tag

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
    return render(
        request,
        "pages/home/public_main.html",
        {
            "list_tags": LIST_TAGS,
            "featured_wiki": FEATURED_WIKI[0],
            "featured_post": FEATURED_POSTS[0],
        },
    )


@login_required
def dashboard(request):
    return render(
        request,
        "pages/home/dashboard.html",
        {
            "page_heading": "Dashboard",
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
            "post_items": FEATURED_POSTS,
        },
    )


@login_required
def community_list(request):
    return render(
        request,
        "pages/community/list.html",
        {
            "page_heading": "Community",
            "list_tags": LIST_TAGS,
            "post_items": FEATURED_POSTS,
        },
    )


@login_required
def wiki_home(request):
    return render(
        request,
        "pages/wiki/search_home.html",
        {
            "page_heading": "Wiki",
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
        },
    )


def integrated_search(request):
    query = request.GET.get("q", "").strip()
    template_name = (
        "partials/search_results.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/search/results.html"
    )
    return render(
        request,
        template_name,
        {
            "page_heading": "Search",
            "query": query,
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
            "post_items": FEATURED_POSTS,
        },
    )


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
    users = list(
        HiveUser.objects.prefetch_related(
            Prefetch(
                "oauth_accounts",
                queryset=OAuthAccount.objects.order_by("-last_login_at", "provider"),
            )
        ).order_by("-created_at")
    )
    return render(
        request,
        "pages/admin/users.html",
        {
            **_build_admin_summary_context(),
            "page_heading": "User Management",
            "admin_section": "users",
            "users": users,
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
        },
    )


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
