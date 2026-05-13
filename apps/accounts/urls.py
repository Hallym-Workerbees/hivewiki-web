from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.login_view, name="login"),
    path("auth/signup/", views.signup_view, name="signup"),
    path("auth/logout/", views.logout_view, name="logout"),
    path(
        "auth/oauth/confirm-existing/",
        views.oauth_confirm_existing_account_view,
        name="oauth_confirm_existing_account",
    ),
    path("auth/timezone/", views.set_timezone_view, name="set_timezone"),
    path("auth/oauth/<str:provider>/", views.oauth_start_view, name="oauth_start"),
    path(
        "me/oauth/<str:provider>/link/",
        views.oauth_link_start_view,
        name="oauth_link_start",
    ),
    path(
        "auth/oauth/<str:provider>/callback/",
        views.oauth_callback_view,
        name="oauth_callback",
    ),
    path("me/", views.mypage_view, name="mypage"),
    path("me/posts/", views.mypage_authored_posts_view, name="mypage_authored_posts"),
    path(
        "me/likes/posts/",
        views.mypage_liked_posts_view,
        name="mypage_liked_posts",
    ),
    path(
        "me/likes/comments/",
        views.mypage_liked_comments_view,
        name="mypage_liked_comments",
    ),
    path(
        "me/bookmarks/posts/",
        views.mypage_bookmarked_posts_view,
        name="mypage_bookmarked_posts",
    ),
    path(
        "me/bookmarks/wiki/",
        views.mypage_bookmarked_wiki_view,
        name="mypage_bookmarked_wiki",
    ),
    path("me/profile/", views.profile_edit_view, name="profile_edit"),
    path(
        "me/profile/image-upload/prepare/",
        views.profile_image_upload_prepare_view,
        name="profile_image_upload_prepare",
    ),
    path("me/password/", views.password_change_view, name="password_change"),
]
