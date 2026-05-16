from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.models import (
    CommentLike,
    Post,
    PostBookmark,
    PostLike,
    PostStatus,
    WikiBookmark,
    WikiDocumentStatus,
)

from .decorators import login_required
from .forms import LoginForm, PasswordChangeForm, ProfileEditForm, SignUpForm
from .models import HiveUser, UserStatus
from .notifications import (
    attach_notification_targets,
    get_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)
from .services import (
    OAUTH_ACTION_LINK,
    PENDING_OAUTH_CONFIRM_SESSION_KEY,
    OAuthError,
    ProfileImageUploadError,
    authenticate_user,
    begin_oauth_flow,
    build_pending_oauth_confirmation,
    build_profile_image_upload_payload,
    create_user,
    exchange_oauth_code_for_profile,
    format_rate_limit_wait_time,
    get_available_oauth_providers,
    get_client_ip,
    get_current_user,
    get_existing_oauth_account_for_profile,
    get_existing_user_for_oauth_email,
    get_login_rate_limit_remaining_seconds,
    get_oauth_provider_config,
    get_or_create_user_from_oauth_profile,
    get_unlinked_oauth_providers,
    get_user_by_email,
    get_user_oauth_accounts,
    inactive_account_message,
    is_login_rate_limited,
    link_oauth_account_to_user,
    login_user,
    logout_user,
    read_pending_oauth_confirmation,
    record_failed_login,
    reset_login_rate_limit,
    set_browser_timezone,
    update_user_password,
)

PROFILE_ACTIVITY_PAGE_SIZE = 20
NOTIFICATION_PAGE_SIZE = 20


def _get_safe_next_url(request):
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


def _redirect_to_login(next_url: str = ""):
    if next_url:
        return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")
    return redirect("login")


def _annotated_profile_posts(queryset):
    return (
        queryset.prefetch_related("tags", "wiki_documents")
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


def _paginate_profile_items(queryset, *, page_number):
    paginator = Paginator(queryset, PROFILE_ACTIVITY_PAGE_SIZE)
    return paginator.get_page(page_number)


def _paginate_notifications(queryset, *, page_number):
    paginator = Paginator(queryset, NOTIFICATION_PAGE_SIZE)
    return paginator.get_page(page_number)


def _profile_visible_posts_filter(user: HiveUser | None, prefix: str = ""):
    visible_filter = Q(**{f"{prefix}status": PostStatus.PUBLISHED})
    if user is not None:
        visible_filter |= Q(
            **{
                f"{prefix}author_user": user,
                f"{prefix}status": PostStatus.DRAFT,
            }
        )
    return visible_filter


def _profile_authored_posts_queryset(user: HiveUser):
    return _annotated_profile_posts(
        Post.objects.filter(
            author_user=user,
            deleted_at__isnull=True,
        )
    )


def _profile_liked_posts_queryset(user: HiveUser):
    return (
        PostLike.objects.filter(
            user=user,
            post__deleted_at__isnull=True,
        )
        .filter(_profile_visible_posts_filter(user, prefix="post__"))
        .select_related("post")
        .order_by("-created_at", "-id")
    )


def _profile_liked_posts_preview(user: HiveUser):
    return list(_profile_liked_posts_queryset(user)[:5])


def _profile_liked_comment_items_queryset(user: HiveUser):
    return (
        CommentLike.objects.filter(
            user=user,
            comment__deleted_at__isnull=True,
            comment__post__deleted_at__isnull=True,
        )
        .filter(_profile_visible_posts_filter(user, prefix="comment__post__"))
        .select_related("comment", "comment__post")
        .order_by("-created_at", "-id")
    )


def _profile_bookmarked_posts_queryset(user: HiveUser):
    return (
        PostBookmark.objects.filter(
            user=user,
            post__deleted_at__isnull=True,
        )
        .filter(_profile_visible_posts_filter(user, prefix="post__"))
        .select_related("post")
        .order_by("-created_at", "-id")
    )


def _profile_bookmarked_posts_preview(user: HiveUser):
    return list(_profile_bookmarked_posts_queryset(user)[:5])


def _profile_bookmarked_wiki_items_queryset(user: HiveUser):
    return (
        WikiBookmark.objects.filter(
            user=user,
            wiki_document__current_revision__isnull=False,
            wiki_document__status=WikiDocumentStatus.PUBLISHED,
        )
        .select_related("wiki_document")
        .order_by("-created_at", "-id")
    )


def _build_profile_activity_context(user: HiveUser) -> dict:
    activity_totals = HiveUser.objects.filter(pk=user.pk).aggregate(
        authored_post_count=Count(
            "posts",
            filter=Q(posts__deleted_at__isnull=True),
            distinct=True,
        ),
        authored_comment_count=Count(
            "comments",
            filter=Q(comments__deleted_at__isnull=True),
            distinct=True,
        ),
        received_post_like_count=Count(
            "posts__post_likes",
            filter=Q(posts__deleted_at__isnull=True),
            distinct=True,
        ),
        received_comment_like_count=Count(
            "comments__comment_likes",
            filter=Q(comments__deleted_at__isnull=True),
            distinct=True,
        ),
        linked_wiki_post_count=Count(
            "posts",
            filter=Q(
                posts__deleted_at__isnull=True,
                posts__wiki_documents__isnull=False,
            ),
            distinct=True,
        ),
    )
    recent_posts = list(_profile_authored_posts_queryset(user)[:5])
    liked_posts = _profile_liked_posts_preview(user)
    liked_comment_items = list(_profile_liked_comment_items_queryset(user)[:5])
    bookmarked_posts = _profile_bookmarked_posts_preview(user)
    bookmarked_wiki_items = list(_profile_bookmarked_wiki_items_queryset(user)[:5])
    return {
        "activity_stats": [
            {
                "label": "작성 글",
                "value": activity_totals["authored_post_count"] or 0,
                "description": "삭제되지 않은 커뮤니티 게시글 수입니다.",
            },
            {
                "label": "작성 댓글",
                "value": activity_totals["authored_comment_count"] or 0,
                "description": "대화에 참여한 댓글 수입니다.",
            },
            {
                "label": "받은 좋아요",
                "value": (activity_totals["received_post_like_count"] or 0)
                + (activity_totals["received_comment_like_count"] or 0),
                "description": "게시글과 댓글이 받은 좋아요 합계입니다.",
            },
            {
                "label": "연결한 위키",
                "value": activity_totals["linked_wiki_post_count"] or 0,
                "description": "게시글에서 참조한 위키가 있는 글 수입니다.",
            },
        ],
        "recent_posts": recent_posts,
        "liked_posts": liked_posts,
        "liked_comment_items": liked_comment_items,
        "bookmarked_posts": bookmarked_posts,
        "bookmarked_wiki_items": bookmarked_wiki_items,
        "recent_posts_url": reverse("mypage_authored_posts"),
        "liked_posts_url": reverse("mypage_liked_posts"),
        "liked_comments_url": reverse("mypage_liked_comments"),
        "bookmarked_posts_url": reverse("mypage_bookmarked_posts"),
        "bookmarked_wiki_url": reverse("mypage_bookmarked_wiki"),
    }


def login_view(request):
    if getattr(request, "current_user", None) is not None:
        return redirect("dashboard")

    form = LoginForm(request.POST or None)
    next_url = _get_safe_next_url(request)
    client_ip = get_client_ip(request)
    oauth_providers = get_available_oauth_providers(request, next_url=next_url)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if is_login_rate_limited(email=email, client_ip=client_ip):
            remaining_seconds = get_login_rate_limit_remaining_seconds(
                email=email,
                client_ip=client_ip,
            )
            form.add_error(
                None,
                f"로그인 시도가 너무 많습니다. {format_rate_limit_wait_time(remaining_seconds)} 후 다시 시도해 주세요.",
            )
            return render(
                request,
                "pages/auth/login.html",
                {
                    "form": form,
                    "next_url": next_url,
                    "oauth_providers": oauth_providers,
                },
            )

        user = authenticate_user(
            email=email,
            password=form.cleaned_data["password"],
        )
        if user is None:
            record_failed_login(email=email, client_ip=client_ip)
            existing_user = get_user_by_email(email)
            if existing_user and existing_user.status != UserStatus.ACTIVE:
                form.add_error(None, inactive_account_message())
            elif (
                existing_user
                and existing_user.oauth_accounts.exists()
                and not existing_user.password_hash
            ):
                form.add_error(
                    None,
                    "이 계정은 OAuth 로그인만 사용할 수 있습니다. 연결된 소셜 로그인으로 접속해 주세요.",
                )
            else:
                form.add_error(None, "이메일 또는 비밀번호가 올바르지 않습니다.")
        else:
            reset_login_rate_limit(email=email, client_ip=client_ip)
            login_user(request, user)
            messages.success(request, f"{user.username}님, 다시 오셨네요.")
            return redirect(next_url or "dashboard")

    return render(
        request,
        "pages/auth/login.html",
        {
            "form": form,
            "next_url": next_url,
            "oauth_providers": oauth_providers,
        },
    )


def signup_view(request):
    if getattr(request, "current_user", None) is not None:
        return redirect("dashboard")

    form = SignUpForm(request.POST or None)
    oauth_providers = get_available_oauth_providers(request)
    if request.method == "POST" and form.is_valid():
        user = create_user(
            username=form.cleaned_data["username"],
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        login_user(request, user)
        messages.success(request, f"{user.username}님, 가입이 완료되었습니다.")
        return redirect("dashboard")

    return render(
        request,
        "pages/auth/signup.html",
        {
            "form": form,
            "oauth_providers": oauth_providers,
        },
    )


@require_POST
def logout_view(request):
    logout_user(request)
    messages.success(request, "로그아웃되었습니다.")
    return redirect("public_main")


@require_POST
def set_timezone_view(request):
    timezone_name = request.POST.get("timezone", "")
    if not set_browser_timezone(request, timezone_name):
        return HttpResponse(status=400)
    return HttpResponse(status=204)


def oauth_start_view(request, provider: str):
    next_url = _get_safe_next_url(request)
    try:
        redirect_url = begin_oauth_flow(
            request,
            provider=provider,
            next_url=next_url,
        )
    except OAuthError as exc:
        messages.error(request, str(exc))
        return redirect("login")
    except KeyError as exc:
        raise Http404 from exc
    return redirect(redirect_url)


@login_required
def oauth_link_start_view(request, provider: str):
    current_user = request.current_user
    try:
        redirect_url = begin_oauth_flow(
            request,
            provider=provider,
            next_url=reverse("mypage"),
            action=OAUTH_ACTION_LINK,
            link_user=current_user,
        )
    except OAuthError as exc:
        messages.error(request, str(exc))
        return redirect("mypage")
    except KeyError as exc:
        raise Http404 from exc
    return redirect(redirect_url)


@require_POST
def oauth_confirm_existing_account_view(request):
    pending_confirmation_token = request.session.get(
        PENDING_OAUTH_CONFIRM_SESSION_KEY, ""
    )
    if not pending_confirmation_token:
        messages.error(
            request, "확인할 OAuth 연동 정보가 없습니다. 다시 시도해 주세요."
        )
        return redirect("login")

    request.session.pop(PENDING_OAUTH_CONFIRM_SESSION_KEY, None)
    try:
        pending_confirmation = read_pending_oauth_confirmation(
            pending_confirmation_token
        )
    except OAuthError as exc:
        messages.error(request, str(exc))
        return redirect("login")

    next_url = pending_confirmation.get("next_url", "")
    decision = request.POST.get("decision", "")
    if decision != "confirm":
        messages.info(request, "OAuth 계정 연결을 취소했습니다.")
        return _redirect_to_login(next_url)

    try:
        user = HiveUser.objects.get(
            id=pending_confirmation["user_id"],
            status=UserStatus.ACTIVE,
        )
        link_oauth_account_to_user(
            user=user,
            provider=pending_confirmation["provider"],
            profile=pending_confirmation["profile"],
        )
    except (HiveUser.DoesNotExist, KeyError, OAuthError) as exc:
        messages.error(
            request,
            str(exc)
            if isinstance(exc, OAuthError)
            else "기존 계정 연결을 완료하지 못했습니다. 다시 시도해 주세요.",
        )
        return _redirect_to_login(next_url)

    login_user(request, user)
    messages.success(request, f"{user.username}님, 소셜 로그인이 완료되었습니다.")
    return redirect(next_url or "dashboard")


def oauth_callback_view(request, provider: str):
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    if not code or not state:
        messages.error(request, "OAuth 응답이 올바르지 않습니다.")
        return redirect("login")

    try:
        get_oauth_provider_config(provider)
        profile, state_data = exchange_oauth_code_for_profile(
            request,
            provider=provider,
            code=code,
            state=state,
        )
        next_url = state_data.get("next_url", "")
        if state_data.get("action") == OAUTH_ACTION_LINK:
            try:
                current_user = get_current_user(request)
                if current_user is None:
                    raise OAuthError(
                        "로그인한 상태에서만 OAuth 계정을 연동할 수 있습니다."
                    )
                link_user_id = state_data.get("link_user_id")
                if str(current_user.id) != link_user_id:
                    raise OAuthError(
                        "연동 대상 계정이 변경되었습니다. 다시 시도해 주세요."
                    )
                link_oauth_account_to_user(
                    user=current_user,
                    provider=provider,
                    profile=profile,
                )
            except OAuthError as exc:
                messages.error(request, str(exc))
                return redirect("mypage")
            messages.success(
                request,
                f"{current_user.username} 계정에 {provider.title()} 로그인을 연결했습니다.",
            )
            return redirect(next_url or "mypage")
        existing_oauth_account = get_existing_oauth_account_for_profile(
            provider=provider,
            profile=profile,
        )
        existing_user = get_existing_user_for_oauth_email(profile)
        if (
            existing_oauth_account is None
            and existing_user is not None
            and existing_user.status == UserStatus.ACTIVE
        ):
            request.session[PENDING_OAUTH_CONFIRM_SESSION_KEY] = (
                build_pending_oauth_confirmation(
                    provider=provider,
                    profile=profile,
                    user_id=existing_user.id,
                    next_url=next_url,
                )
            )
            return render(
                request,
                "pages/auth/oauth_confirm_existing_account.html",
                {
                    "provider": provider,
                    "provider_label": provider.title(),
                    "existing_user": existing_user,
                    "next_url": next_url,
                },
            )
        user = get_or_create_user_from_oauth_profile(provider=provider, profile=profile)
    except OAuthError as exc:
        messages.error(request, str(exc))
        return redirect("login")
    except KeyError as exc:
        raise Http404 from exc

    login_user(request, user)
    messages.success(request, f"{user.username}님, 소셜 로그인이 완료되었습니다.")
    return redirect(next_url or "dashboard")


@login_required
def mypage_view(request):
    oauth_accounts = list(get_user_oauth_accounts(request.current_user))
    activity_context = _build_profile_activity_context(request.current_user)
    return render(
        request,
        "pages/user/mypage.html",
        {
            "page_heading": "My Page",
            "profile_user": request.current_user,
            "oauth_accounts": oauth_accounts,
            "available_oauth_link_providers": get_unlinked_oauth_providers(
                request,
                user=request.current_user,
            ),
            "password_login_disabled": request.current_user.password_hash is None,
            **activity_context,
        },
    )


def _render_profile_activity_list(
    request,
    *,
    page_heading: str,
    title: str,
    description: str,
    page_obj,
    list_type: str,
):
    return render(
        request,
        "pages/user/activity_list.html",
        {
            "page_heading": page_heading,
            "title": title,
            "description": description,
            "page_obj": page_obj,
            "list_type": list_type,
        },
    )


@login_required
def mypage_authored_posts_view(request):
    page_obj = _paginate_profile_items(
        _profile_authored_posts_queryset(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    return _render_profile_activity_list(
        request,
        page_heading="My Posts",
        title="내가 쓴 글",
        description="작성한 커뮤니티 게시글 목록입니다.",
        page_obj=page_obj,
        list_type="posts",
    )


@login_required
def mypage_liked_posts_view(request):
    page_obj = _paginate_profile_items(
        _profile_liked_posts_queryset(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    return _render_profile_activity_list(
        request,
        page_heading="Liked Posts",
        title="좋아요한 게시글",
        description="좋아요를 누른 게시글을 최신순으로 확인할 수 있습니다.",
        page_obj=page_obj,
        list_type="liked_posts",
    )


@login_required
def mypage_liked_comments_view(request):
    page_obj = _paginate_profile_items(
        _profile_liked_comment_items_queryset(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    return _render_profile_activity_list(
        request,
        page_heading="Liked Comments",
        title="좋아요한 댓글",
        description="좋아요를 누른 댓글과 해당 게시글로 바로 이동할 수 있습니다.",
        page_obj=page_obj,
        list_type="liked_comments",
    )


@login_required
def mypage_bookmarked_posts_view(request):
    page_obj = _paginate_profile_items(
        _profile_bookmarked_posts_queryset(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    return _render_profile_activity_list(
        request,
        page_heading="Bookmarked Posts",
        title="북마크한 게시글",
        description="나중에 다시 보려 저장한 커뮤니티 게시글 목록입니다.",
        page_obj=page_obj,
        list_type="bookmarked_posts",
    )


@login_required
def mypage_bookmarked_wiki_view(request):
    page_obj = _paginate_profile_items(
        _profile_bookmarked_wiki_items_queryset(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    return _render_profile_activity_list(
        request,
        page_heading="Bookmarked Wiki",
        title="북마크한 위키",
        description="저장해 둔 위키 문서를 최신순으로 확인할 수 있습니다.",
        page_obj=page_obj,
        list_type="bookmarked_wiki",
    )


@login_required
def mypage_notifications_view(request):
    page_obj = _paginate_notifications(
        get_notifications_for_user(request.current_user),
        page_number=request.GET.get("page", "1"),
    )
    notifications = attach_notification_targets(page_obj.object_list)
    next_page_url = (
        f"{reverse('mypage_notifications')}?page={page_obj.next_page_number()}"
        if page_obj.has_next()
        else ""
    )
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/notifications_page.html",
            {
                "notifications": notifications,
                "next_page_url": next_page_url,
            },
        )
    return render(
        request,
        "pages/user/notifications.html",
        {
            "page_heading": "Notifications",
            "notifications": notifications,
            "page_obj": page_obj,
            "next_page_url": next_page_url,
        },
    )


@login_required
@require_POST
def notifications_mark_all_read_view(request):
    mark_all_notifications_read(request.current_user)
    if request.headers.get("HX-Request") == "true":
        page_obj = _paginate_notifications(
            get_notifications_for_user(request.current_user),
            page_number=request.GET.get("page", "1"),
        )
        return render(
            request,
            "partials/notifications_panel.html",
            {
                "notifications": attach_notification_targets(page_obj.object_list),
                "page_obj": page_obj,
                "next_page_url": (
                    f"{reverse('mypage_notifications')}?page={page_obj.next_page_number()}"
                    if page_obj.has_next()
                    else ""
                ),
            },
        )
    return redirect(request.POST.get("next") or "mypage_notifications")


@login_required
@require_POST
def notification_mark_read_view(request, notification_id):
    notification = get_object_or_404(
        get_notifications_for_user(request.current_user),
        pk=notification_id,
    )
    mark_notification_read(notification)
    if request.headers.get("HX-Request") == "true":
        page_obj = _paginate_notifications(
            get_notifications_for_user(request.current_user),
            page_number=request.GET.get("page", "1"),
        )
        return render(
            request,
            "partials/notifications_panel.html",
            {
                "notifications": attach_notification_targets(page_obj.object_list),
                "page_obj": page_obj,
                "next_page_url": (
                    f"{reverse('mypage_notifications')}?page={page_obj.next_page_number()}"
                    if page_obj.has_next()
                    else ""
                ),
            },
        )
    return redirect(request.POST.get("next") or "mypage_notifications")


@login_required
def profile_edit_view(request):
    form = ProfileEditForm(request.POST or None, instance=request.current_user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "프로필이 업데이트되었습니다.")
        return redirect("mypage")

    return render(
        request,
        "pages/user/profile_edit.html",
        {
            "page_heading": "Profile",
            "form": form,
        },
    )


@login_required
@require_POST
def profile_image_upload_prepare_view(request):
    try:
        payload = build_profile_image_upload_payload(
            user=request.current_user,
            filename=request.POST.get("filename", ""),
            content_type=request.POST.get("content_type", ""),
        )
    except ProfileImageUploadError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(payload)


@login_required
def password_change_view(request):
    if request.current_user.password_hash is None:
        messages.error(
            request,
            "비밀번호가 설정되지 않은 계정입니다. OAuth 로그인만 사용할 수 있습니다.",
        )
        return redirect("mypage")
    form = PasswordChangeForm(request.POST or None, user=request.current_user)
    if request.method == "POST" and form.is_valid():
        update_user_password(
            user=request.current_user,
            new_password=form.cleaned_data["new_password"],
        )
        messages.success(request, "비밀번호가 변경되었습니다.")
        return redirect("mypage")

    return render(
        request,
        "pages/user/password_change.html",
        {
            "page_heading": "Password",
            "form": form,
        },
    )
