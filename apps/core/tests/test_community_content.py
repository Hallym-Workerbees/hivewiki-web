from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.community_content import (
    build_post_excerpt,
    build_post_markdown,
    extract_first_image_url,
    extract_post_render_parts,
    extract_post_title_and_body,
    strip_post_leading_title,
)
from apps.core.models import Post


class CommunityContentTests(SimpleTestCase):
    def test_build_post_markdown_returns_body_as_is(self):
        markdown = build_post_markdown("첫 문단입니다.")

        self.assertEqual(markdown, "첫 문단입니다.")

    def test_build_post_markdown_converts_html_image_to_markdown(self):
        markdown = build_post_markdown(
            '<img alt="대체텍스트" src="https://attachment.hive-wiki.com/community-images/tmp/example.png">'
        )

        self.assertEqual(
            markdown,
            "![대체텍스트](https://attachment.hive-wiki.com/community-images/tmp/example.png)",
        )

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

    def test_extract_post_render_parts_returns_title_body_and_excerpt(self):
        title, body, excerpt = extract_post_render_parts(
            "# 문서화 대상 정리\n\n반복되는 질문과 운영 이슈를 모아 위키 후보를 고릅니다."
        )

        self.assertEqual(title, "문서화 대상 정리")
        self.assertEqual(body, "반복되는 질문과 운영 이슈를 모아 위키 후보를 고릅니다.")
        self.assertEqual(
            excerpt, "반복되는 질문과 운영 이슈를 모아 위키 후보를 고릅니다."
        )

    def test_post_render_properties_share_cached_parse_result(self):
        post = Post(content_markdown="# 제목\n\n본문")

        with patch(
            "apps.core.models.extract_post_render_parts",
            return_value=("제목", "본문", "요약"),
        ) as extract_parts:
            self.assertEqual(post.title, "제목")
            self.assertEqual(post.body_markdown, "본문")
            self.assertEqual(post.summary, "요약")
            self.assertEqual(post.summary, "요약")

        extract_parts.assert_called_once_with("# 제목\n\n본문")

    def test_post_render_properties_recompute_when_content_changes(self):
        post = Post(content_markdown="첫 본문")

        with patch(
            "apps.core.models.extract_post_render_parts",
            side_effect=[
                ("첫 제목", "첫 본문", "첫 요약"),
                ("두 번째 제목", "두 번째 본문", "두 번째 요약"),
            ],
        ) as extract_parts:
            self.assertEqual(post.summary, "첫 요약")
            post.content_markdown = "두 번째 본문"
            self.assertEqual(post.summary, "두 번째 요약")

        self.assertEqual(extract_parts.call_count, 2)

    def test_extract_first_image_url_reads_html_image_for_legacy_content(self):
        image_url = extract_first_image_url(
            '<img alt="대체텍스트" src="https://attachment.hive-wiki.com/community-images/tmp/example.png">'
        )

        self.assertEqual(
            image_url,
            "https://attachment.hive-wiki.com/community-images/tmp/example.png",
        )
