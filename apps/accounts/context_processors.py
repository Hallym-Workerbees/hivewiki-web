from .services import get_current_user


def current_user(request):
    return {
        "current_user": getattr(request, "current_user", None)
        or get_current_user(request),
    }
