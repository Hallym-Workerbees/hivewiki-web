from functools import wraps
from urllib.parse import urlencode

from django.shortcuts import redirect


def login_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if getattr(request, "current_user", None) is None:
            query_string = urlencode({"next": request.get_full_path()})
            return redirect(f"/auth/login/?{query_string}")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
