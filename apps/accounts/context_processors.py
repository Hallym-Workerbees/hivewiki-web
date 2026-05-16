from .notifications import get_unread_notification_count
from .services import get_current_user


def current_user(request):
    current_user = getattr(request, "current_user", None) or get_current_user(request)
    return {
        "current_user": current_user,
        "notification_unread_count": get_unread_notification_count(current_user),
    }
