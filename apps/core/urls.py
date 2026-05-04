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
    path("wiki/", views.wiki_home, name="wiki_home"),
    path("wiki/<slug:slug>/", views.wiki_detail, name="wiki_detail"),
    path("search/", views.integrated_search, name="integrated_search"),
]
