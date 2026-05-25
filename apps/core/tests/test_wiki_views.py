from django.test import TestCase, override_settings
from django.urls import reverse
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
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
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
        self.assertContains(response, "&lt;script&gt;alert('xss')&lt;/script&gt;")
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
        self.assertNotContains(response, 'style="')

    def test_wiki_detail_adds_safe_rel_to_links(self):
        document = WikiDocument.objects.create(
            title="외부 링크 문서",
            slug="external-link-doc",
            summary="외부 링크 보안 속성을 확인합니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="[문서 링크](https://example.com)",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/external-link-doc/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<a href="https://example.com" rel="noopener noreferrer">문서 링크</a>',
            html=True,
        )

    def test_wiki_detail_renders_code_blocks_without_double_escaped_entities(self):
        document = WikiDocument.objects.create(
            title="코드 블록 문서",
            slug="code-block-doc",
            summary="코드 블록 렌더링을 확인합니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="""```python
def promote_question_to_wiki(question, chunks):
    if question.repeat_count < 2:
        return "keep_in_community"
```
""",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        response = self.client.get("/wiki/code-block-doc/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&quot;keep_in_community&quot;")
        self.assertContains(response, '<span class="o">&lt;</span>', html=False)
        self.assertNotContains(response, "&amp;quot;keep_in_community&amp;quot;")
        self.assertNotContains(response, "&amp;lt;")

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

    def test_wiki_pages_support_unicode_slugs(self):
        document = WikiDocument.objects.create(
            title="2026 2학기 학사신청 전공배정 소속변경 및 복수전공 안내",
            slug="2026-2학기-학사신청전공배정-소속변경-및-복수전공-안내",
            summary="한글 슬러그 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        revision = WikiRevision.objects.create(
            wiki_document=document,
            revision_number=1,
            content_markdown="## 신청 안내",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])

        detail_url = reverse("wiki_detail", kwargs={"slug": document.slug})
        bookmark_url = reverse("wiki_bookmark_toggle", kwargs={"slug": document.slug})

        self.assertEqual(
            detail_url,
            "/wiki/2026-2%ED%95%99%EA%B8%B0-%ED%95%99%EC%82%AC%EC%8B%A0%EC%B2%AD%EC%A0%84%EA%B3%B5%EB%B0%B0%EC%A0%95-%EC%86%8C%EC%86%8D%EB%B3%80%EA%B2%BD-%EB%B0%8F-%EB%B3%B5%EC%88%98%EC%A0%84%EA%B3%B5-%EC%95%88%EB%82%B4/",
        )
        self.assertEqual(
            bookmark_url,
            "/wiki/2026-2%ED%95%99%EA%B8%B0-%ED%95%99%EC%82%AC%EC%8B%A0%EC%B2%AD%EC%A0%84%EA%B3%B5%EB%B0%B0%EC%A0%95-%EC%86%8C%EC%86%8D%EB%B3%80%EA%B2%BD-%EB%B0%8F-%EB%B3%B5%EC%88%98%EC%A0%84%EA%B3%B5-%EC%95%88%EB%82%B4/bookmark/",
        )

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "신청 안내")

    def test_wiki_detail_requires_current_revision_for_published_document(self):
        WikiDocument.objects.create(
            title="리비전 없는 공개 문서",
            slug="published-without-revision",
            summary="공개 문서는 현재 리비전이 있어야 합니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )

        response = self.client.get("/wiki/published-without-revision/")

        self.assertEqual(response.status_code, 404)
