from .services import get_current_user


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.current_user = get_current_user(request)
        return self.get_response(request)
