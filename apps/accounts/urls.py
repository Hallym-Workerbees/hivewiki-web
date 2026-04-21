from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.login_view, name="login"),
    path("auth/signup/", views.signup_view, name="signup"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("me/", views.mypage_view, name="mypage"),
    path("me/profile/", views.profile_edit_view, name="profile_edit"),
    path("me/password/", views.password_change_view, name="password_change"),
]
