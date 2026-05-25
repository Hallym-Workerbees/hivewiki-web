from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import HiveUser, UserStatus
from apps.core.models import (
    Post,
    PostStatus,
    Tag,
    TagType,
    WikiDocument,
    WikiDocumentStatus,
    WikiGenerationType,
    WikiRevision,
)


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-search-test-cache",
        }
    },
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class SearchViewTests(TestCase):
    def test_integrated_search_shows_matching_wiki_documents_and_posts(self):
        matching_document = WikiDocument.objects.create(
            title="커뮤니티 질문을 위키로 전환하는 기준",
            slug="community-to-wiki-criteria",
            summary="질문을 문서화하는 기준입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        matching_revision = WikiRevision.objects.create(
            wiki_document=matching_document,
            revision_number=1,
            content_markdown="## 선정 기준\n\n- 반복 질문",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        matching_document.current_revision = matching_revision
        matching_document.save(update_fields=["current_revision"])

        non_matching_document = WikiDocument.objects.create(
            title="캡스톤 위키 운영 가이드",
            slug="capstone-wiki-guide",
            summary="문서 운영 가이드입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        non_matching_revision = WikiRevision.objects.create(
            wiki_document=non_matching_document,
            revision_number=1,
            content_markdown="## 운영 원칙",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        non_matching_document.current_revision = non_matching_revision
        non_matching_document.save(update_fields=["current_revision"])

        author = HiveUser.objects.create(
            username="search_author",
            email="search-author@example.com",
            status=UserStatus.ACTIVE,
        )
        Post.objects.create(
            author_user=author,
            content_markdown="# 선정 기준 논의\n\n반복 질문을 문서화하는 기준을 정리합니다.",
            status=PostStatus.PUBLISHED,
        )
        Post.objects.create(
            author_user=author,
            content_markdown="# 운영 회고\n\n주간 운영 이슈를 정리합니다.",
            status=PostStatus.PUBLISHED,
        )

        response = self.client.get("/search/", {"q": "선정 기준"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "통합 검색")
        self.assertContains(response, "커뮤니티 질문을 위키로 전환하는 기준")
        self.assertContains(response, "반복 질문을 문서화하는 기준을 정리합니다.")
        self.assertNotContains(response, "캡스톤 위키 운영 가이드")
        self.assertNotContains(response, "운영 회고")
        self.assertContains(response, "게시글")
        self.assertContains(response, "문서 1건 · 게시글 1건")

    def test_integrated_search_shows_total_count_before_limit(self):
        for index in range(18):
            document = WikiDocument.objects.create(
                title=f"운영 기준 문서 {index}",
                slug=f"operations-guide-{index}",
                summary="운영 기준을 정리한 문서입니다.",
                status=WikiDocumentStatus.PUBLISHED,
                updated_at=timezone.now() + timezone.timedelta(minutes=index),
            )
            revision = WikiRevision.objects.create(
                wiki_document=document,
                revision_number=1,
                content_markdown="## 운영 기준",
                generation_type=WikiGenerationType.AI,
                generation_model="gpt-5.5",
            )
            document.current_revision = revision
            document.save(update_fields=["current_revision"])

        response = self.client.get("/search/", {"q": "운영 기준"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "문서 18건")
        self.assertContains(response, "18건")
        self.assertContains(response, "운영 기준 문서 17")
        self.assertNotContains(response, "운영 기준 문서 0")

    def test_integrated_search_matches_post_tags_and_linked_wiki_titles(self):
        author = HiveUser.objects.create(
            username="post_author",
            email="post-search@example.com",
            status=UserStatus.ACTIVE,
        )
        linked_document = WikiDocument.objects.create(
            title="캡스톤 발표 준비",
            slug="capstone-demo-prep",
            summary="발표 준비 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        linked_revision = WikiRevision.objects.create(
            wiki_document=linked_document,
            revision_number=1,
            content_markdown="## 발표 체크리스트",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        linked_document.current_revision = linked_revision
        linked_document.save(update_fields=["current_revision"])
        tag = Tag.objects.create(
            name="발표", slug="presentation", tag_type=TagType.USER
        )

        matching_post = Post.objects.create(
            author_user=author,
            content_markdown="# 데모 일정 공유\n\n이번 주 준비 상황을 정리합니다.",
            status=PostStatus.PUBLISHED,
        )
        matching_post.tags.add(tag)
        matching_post.wiki_documents.add(linked_document)

        response = self.client.get("/search/", {"q": "발표"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "이번 주 준비 상황을 정리합니다.")
        self.assertContains(response, "#발표")
        self.assertContains(response, "캡스톤 발표 준비")
        self.assertContains(response, "게시글 1건")

    def test_wiki_home_filters_documents_for_htmx_requests(self):
        matching_document = WikiDocument.objects.create(
            title="운영 회고 문서",
            slug="retrospective-guide",
            summary="운영 회고를 정리한 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        matching_revision = WikiRevision.objects.create(
            wiki_document=matching_document,
            revision_number=1,
            content_markdown="## 회고 항목",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        matching_document.current_revision = matching_revision
        matching_document.save(update_fields=["current_revision"])

        response = self.client.get(
            "/wiki/",
            {"q": "회고"},
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"회고" 검색 결과')
        self.assertContains(response, "운영 회고 문서")

    def test_wiki_home_full_page_keeps_query_in_search_input(self):
        document = WikiDocument.objects.create(
            title="운영 회고 문서",
            slug="retrospective-guide",
            summary="운영 회고를 정리한 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="## 회고 항목",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/", {"q": "회고"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="회고"', html=False)

    def test_wiki_home_paginates_full_page_results(self):
        for index in range(9):
            document = WikiDocument.objects.create(
                title=f"운영 문서 {index}",
                slug=f"ops-doc-{index}",
                summary="페이지네이션 확인용 문서입니다.",
                status=WikiDocumentStatus.PUBLISHED,
                updated_at=timezone.now() + timezone.timedelta(minutes=index),
            )
            revision = WikiRevision.objects.create(
                wiki_document=document,
                revision_number=1,
                content_markdown="## 운영 문서",
                generation_type=WikiGenerationType.AI,
                generation_model="gpt-5.5",
            )
            document.current_revision = revision
            document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/", {"page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "페이지 2 / 2")
        self.assertContains(response, "운영 문서 0")
        self.assertNotContains(response, "운영 문서 8")

    def test_wiki_home_paginates_htmx_results_with_query(self):
        for index in range(9):
            document = WikiDocument.objects.create(
                title=f"회고 문서 {index}",
                slug=f"retro-doc-{index}",
                summary="회고 검색 결과입니다.",
                status=WikiDocumentStatus.PUBLISHED,
                updated_at=timezone.now() + timezone.timedelta(minutes=index),
            )
            revision = WikiRevision.objects.create(
                wiki_document=document,
                revision_number=1,
                content_markdown="## 회고 항목",
                generation_type=WikiGenerationType.AI,
                generation_model="gpt-5.5",
            )
            document.current_revision = revision
            document.save(update_fields=["current_revision"])

        response = self.client.get(
            "/wiki/",
            {"q": "회고", "page": 2},
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "페이지 2 / 2")
        self.assertContains(response, 'hx-get="/wiki/?q=%ED%9A%8C%EA%B3%A0"')
        self.assertContains(response, "회고 문서 0")
        self.assertNotContains(response, "회고 문서 8")

    def test_integrated_search_returns_empty_state_for_blank_htmx_query(self):
        response = self.client.get(
            "/search/",
            {"q": ""},
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "검색어를 입력해 주세요")
        self.assertContains(
            response,
            "찾고 싶은 문서 제목, 요약, 본문 키워드를 입력하면 결과를 바로 보여줍니다.",
        )

    def test_integrated_search_shows_recent_documents_when_query_is_blank(self):
        document = WikiDocument.objects.create(
            title="최근 운영 문서",
            slug="recent-operations-doc",
            summary="최근 업데이트된 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="## 최근 변경 사항",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        author = HiveUser.objects.create(
            username="recent_author",
            email="recent-post@example.com",
            status=UserStatus.ACTIVE,
        )
        Post.objects.create(
            author_user=author,
            content_markdown="# 최근 커뮤니티 글\n\n최근 공개된 게시글입니다.",
            status=PostStatus.PUBLISHED,
        )

        response = self.client.get("/search/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "최근 업데이트된 문서를 둘러보고, 필요한 경우 바로 검색으로 좁혀갈 수 있습니다.",
        )
        self.assertContains(response, "최근 운영 문서")
        self.assertContains(response, "최근 공개된 게시글입니다.")
        self.assertNotContains(response, "검색어를 입력해 주세요")

    def test_integrated_search_full_page_keeps_query_in_search_input(self):
        response = self.client.get(reverse("integrated_search"), {"q": "회고"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="회고"', html=False)
