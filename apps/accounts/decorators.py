from functools import wraps
from urllib.parse import urlencode

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .models import UserRole


def login_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if getattr(request, "current_user", None) is None:
            query_string = urlencode({"next": request.get_full_path()})
            return redirect(f"/auth/login/?{query_string}")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if getattr(request, "current_user", None) is None:
            query_string = urlencode({"next": request.get_full_path()})
            return redirect(f"/auth/login/?{query_string}")
        if request.current_user.role != UserRole.ADMIN:
            return HttpResponseForbidden("관리자만 접근할 수 있습니다.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
