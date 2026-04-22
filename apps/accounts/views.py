from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import login_required
from .forms import LoginForm, PasswordChangeForm, ProfileEditForm, SignUpForm
from .services import (
    authenticate_user,
    create_user,
    format_rate_limit_wait_time,
    get_client_ip,
    get_login_rate_limit_remaining_seconds,
    is_login_rate_limited,
    login_user,
    logout_user,
    record_failed_login,
    reset_login_rate_limit,
    update_user_password,
)


def _get_safe_next_url(request):
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


def login_view(request):
    if getattr(request, "current_user", None) is not None:
        return redirect("dashboard")

    form = LoginForm(request.POST or None)
    next_url = _get_safe_next_url(request)
    client_ip = get_client_ip(request)
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
                },
            )

        user = authenticate_user(
            email=email,
            password=form.cleaned_data["password"],
        )
        if user is None:
            record_failed_login(email=email, client_ip=client_ip)
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
        },
    )


def signup_view(request):
    if getattr(request, "current_user", None) is not None:
        return redirect("dashboard")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = create_user(
            username=form.cleaned_data["username"],
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        login_user(request, user)
        messages.success(request, f"{user.username}님, 가입이 완료되었습니다.")
        return redirect("dashboard")

    return render(request, "pages/auth/signup.html", {"form": form})


@require_POST
def logout_view(request):
    logout_user(request)
    messages.success(request, "로그아웃되었습니다.")
    return redirect("public_main")


@login_required
def mypage_view(request):
    return render(
        request,
        "pages/user/mypage.html",
        {
            "page_heading": "My Page",
            "profile_user": request.current_user,
        },
    )


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
def password_change_view(request):
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
