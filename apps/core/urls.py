from django.urls import path

from . import views

urlpatterns = [
    path("", views.public_main, name="public_main"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/admin/", views.admin_console, name="admin_console"),
    path(
        "dashboard/admin/users/",
        views.admin_user_management,
        name="admin_user_management",
    ),
    path(
        "dashboard/admin/users/<uuid:user_id>/action/",
        views.admin_user_action,
        name="admin_user_action",
    ),
    path(
        "dashboard/admin/tags/", views.admin_tag_management, name="admin_tag_management"
    ),
    path(
        "dashboard/admin/ingestion/",
        views.admin_ingestion_management,
        name="admin_ingestion_management",
    ),
    path(
        "dashboard/admin/content/",
        views.admin_content_management,
        name="admin_content_management",
    ),
    path(
        "dashboard/admin/content/posts/<uuid:post_id>/action/",
        views.admin_post_action,
        name="admin_post_action",
    ),
    path(
        "dashboard/admin/content/wiki/<uuid:wiki_id>/action/",
        views.admin_wiki_action,
        name="admin_wiki_action",
    ),
    path(
        "dashboard/admin/tags/<uuid:tag_id>/edit/",
        views.admin_tag_edit_modal,
        name="admin_tag_edit_modal",
    ),
    path(
        "dashboard/admin/sources/<int:source_id>/edit/",
        views.admin_source_edit_modal,
        name="admin_source_edit_modal",
    ),
    path("community/", views.community_list, name="community_list"),
    path("community/<uuid:post_id>/", views.community_detail, name="community_detail"),
    path(
        "community/<uuid:post_id>/edit/",
        views.community_post_edit,
        name="community_post_edit",
    ),
    path(
        "community/<uuid:post_id>/like/",
        views.community_post_like_toggle,
        name="community_post_like_toggle",
    ),
    path(
        "community/<uuid:post_id>/bookmark/",
        views.community_post_bookmark_toggle,
        name="community_post_bookmark_toggle",
    ),
    path(
        "community/<uuid:post_id>/comments/",
        views.community_comment_create,
        name="community_comment_create",
    ),
    path(
        "community/<uuid:post_id>/comments/<uuid:comment_id>/like/",
        views.community_comment_like_toggle,
        name="community_comment_like_toggle",
    ),
    path(
        "community/<uuid:post_id>/comments/<uuid:comment_id>/edit/",
        views.community_comment_edit,
        name="community_comment_edit",
    ),
    path(
        "community/<uuid:post_id>/comments/<uuid:comment_id>/children/",
        views.community_comment_children,
        name="community_comment_children",
    ),
    path(
        "community/wiki-picker/",
        views.community_wiki_picker,
        name="community_wiki_picker",
    ),
    path("wiki/", views.wiki_home, name="wiki_home"),
    path(
        "wiki/<str:slug>/bookmark/",
        views.wiki_bookmark_toggle,
        name="wiki_bookmark_toggle",
    ),
    path("wiki/<str:slug>/", views.wiki_detail, name="wiki_detail"),
    path("search/", views.integrated_search, name="integrated_search"),
]
