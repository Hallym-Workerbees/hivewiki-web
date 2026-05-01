from django.conf import settings
from django.utils import timezone

from .services import TIMEZONE_SESSION_KEY, get_current_user


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone_name = request.session.get(TIMEZONE_SESSION_KEY) or settings.TIME_ZONE
        timezone.activate(timezone_name)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.current_user = get_current_user(request)
        return self.get_response(request)
