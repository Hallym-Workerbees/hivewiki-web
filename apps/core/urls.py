from django.urls import path

from . import views

urlpatterns = [
    path("", views.public_main, name="public_main"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("community/", views.community_list, name="community_list"),
    path("wiki/", views.wiki_home, name="wiki_home"),
    path("search/", views.integrated_search, name="integrated_search"),
]
