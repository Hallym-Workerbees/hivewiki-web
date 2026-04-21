from django.shortcuts import render

from apps.accounts.decorators import login_required

LIST_TAGS = ["지식", "협업", "캠퍼스"]

FEATURED_WIKI = [
    {
        "category": "문서",
        "updated_at": "5분 전",
        "title": "캡스톤 위키 운영 가이드",
        "summary": "프로젝트 문서를 어떻게 축적하고 연결할지에 대한 기본 원칙과 운영 흐름을 정리한 문서입니다.",
        "tags": ["운영", "가이드", "온보딩"],
        "url": "/wiki/",
    },
    {
        "category": "요약",
        "updated_at": "오늘",
        "title": "커뮤니티 질문을 문서로 전환하는 기준",
        "summary": "질문, 답변, 회고를 어떤 조건에서 위키 문서로 승격할지에 대한 실무 기준을 정리합니다.",
        "tags": ["정책", "정리", "문서화"],
        "url": "/wiki/",
    },
]

FEATURED_POSTS = [
    {
        "author": "제품팀",
        "created_at": "방금 전",
        "title": "이번 주에 문서화가 필요한 이슈를 모아봅시다",
        "summary": "흩어진 질문과 답변을 한 번에 정리하기 위한 스레드입니다. 커뮤니티와 위키의 연결 지점을 찾는 용도입니다.",
        "tags": ["질문", "정리", "협업"],
        "comment_count": "8",
        "url": "/community/",
    },
    {
        "author": "운영자",
        "created_at": "1시간 전",
        "title": "검색 첫 화면에서 필요한 정보 구조 의견 받습니다",
        "summary": "사용자가 무엇을 먼저 보게 해야 하는지, 최신 문서와 커뮤니티 글의 비중은 어느 정도가 적절한지 논의합니다.",
        "tags": ["검색", "UX", "피드백"],
        "comment_count": "14",
        "url": "/community/",
    },
]


def public_main(request):
    return render(
        request,
        "pages/home/public_main.html",
        {
            "list_tags": LIST_TAGS,
            "featured_wiki": FEATURED_WIKI[0],
            "featured_post": FEATURED_POSTS[0],
        },
    )


@login_required
def dashboard(request):
    return render(
        request,
        "pages/home/dashboard.html",
        {
            "page_heading": "Dashboard",
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
            "post_items": FEATURED_POSTS,
        },
    )


@login_required
def community_list(request):
    return render(
        request,
        "pages/community/list.html",
        {
            "page_heading": "Community",
            "list_tags": LIST_TAGS,
            "post_items": FEATURED_POSTS,
        },
    )


@login_required
def wiki_home(request):
    return render(
        request,
        "pages/wiki/search_home.html",
        {
            "page_heading": "Wiki",
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
        },
    )


def integrated_search(request):
    query = request.GET.get("q", "").strip()
    template_name = (
        "partials/search_results.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/search/results.html"
    )
    return render(
        request,
        template_name,
        {
            "page_heading": "Search",
            "query": query,
            "list_tags": LIST_TAGS,
            "wiki_items": FEATURED_WIKI,
            "post_items": FEATURED_POSTS,
        },
    )
