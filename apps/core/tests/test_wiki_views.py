from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import (
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
            "LOCATION": "hivewiki-wiki-test-cache",
        }
    },
)
class WikiViewTests(TestCase):
    def test_wiki_home_links_to_detail_page(self):
        document = WikiDocument.objects.create(
            title="캡스톤 위키 운영 가이드",
            slug="capstone-wiki-guide",
            summary="문서 수집과 승격 기준을 정리한 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="# 캡스톤 위키 운영 가이드",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/wiki/capstone-wiki-guide/")

    def test_wiki_detail_renders_current_revision(self):
        document = WikiDocument.objects.create(
            title="커뮤니티 질문을 위키로 전환하는 기준",
            slug="community-to-wiki-criteria",
            summary="질문을 위키 문서로 만드는 기준입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="## 선정 기준\n\n- 반복 질문\n\n<script>alert('xss')</script>",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/community-to-wiki-criteria/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "커뮤니티 질문을 위키로 전환하는 기준")
        self.assertContains(response, '<h2 id="선정-기준">선정 기준</h2>', html=True)
        self.assertContains(response, "<li>반복 질문</li>", html=True)
        self.assertContains(
            response, "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
        )
        self.assertContains(response, "data-toc-link")
        self.assertContains(response, 'href="#선정-기준"')
        self.assertContains(response, "문서 공유")
        self.assertContains(response, "읽기용 복사")
        self.assertContains(response, "에이전트용 복사")
        self.assertNotContains(response, "슬러그")
        self.assertContains(
            response,
            'data-copy-label="공유 링크"',
        )
        self.assertContains(
            response,
            'data-copy-label="에이전트용 사본"',
        )
        self.assertContains(response, 'data-copy-success-text="링크 복사됨!"')
        self.assertContains(response, 'id="human-copy"')

    def test_wiki_detail_does_not_repeat_document_title_from_leading_h1(self):
        document = WikiDocument.objects.create(
            title="커뮤니티 질문을 위키로 전환하는 기준",
            slug="community-to-wiki-criteria",
            summary="질문을 위키 문서로 만드는 기준입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="# 커뮤니티 질문을 위키로 전환하는 기준\n\n## 선정 기준",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/community-to-wiki-criteria/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            '<h1 id="커뮤니티-질문을-위키로-전환하는-기준">커뮤니티 질문을 위키로 전환하는 기준</h1>',
            html=True,
        )
        self.assertContains(response, '<h2 id="선정-기준">선정 기준</h2>', html=True)

    def test_wiki_pages_are_public(self):
        document = WikiDocument.objects.create(
            title="공개 위키 문서",
            slug="public-wiki-doc",
            summary="로그인 없이 읽을 수 있어야 합니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="## 공개 섹션",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        home_response = self.client.get("/wiki/")
        detail_response = self.client.get("/wiki/public-wiki-doc/")

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
