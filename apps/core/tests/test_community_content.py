from django.test import SimpleTestCase

from apps.core.community_content import (
    build_post_excerpt,
    build_post_markdown,
    extract_post_title_and_body,
    strip_post_leading_title,
)


class CommunityContentTests(SimpleTestCase):
    def test_build_post_markdown_returns_body_as_is(self):
        markdown = build_post_markdown("첫 문단입니다.")

        self.assertEqual(markdown, "첫 문단입니다.")

    def test_extract_post_title_and_body_reads_leading_h1(self):
        title, body = extract_post_title_and_body(
            "# 이번 주 문서화 대상\n\n질문을 모아봅시다."
        )

        self.assertEqual(title, "이번 주 문서화 대상")
        self.assertEqual(body, "질문을 모아봅시다.")

    def test_build_post_excerpt_uses_body_without_title(self):
        excerpt = build_post_excerpt(
            "# 문서화 대상 정리\n\n반복되는 질문과 운영 이슈를 모아 위키 후보를 고릅니다."
        )

        self.assertEqual(
            excerpt, "반복되는 질문과 운영 이슈를 모아 위키 후보를 고릅니다."
        )

    def test_strip_post_leading_title_keeps_body_only_for_legacy_posts(self):
        body = strip_post_leading_title("# 예전 제목\n\n본문만 보여야 합니다.")

        self.assertEqual(body, "본문만 보여야 합니다.")
