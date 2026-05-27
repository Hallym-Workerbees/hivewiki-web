from django.test import SimpleTestCase

from apps.core.markdown_rendering import build_rendered_markdown


class MarkdownRenderingTests(SimpleTestCase):
    def test_build_rendered_markdown_renders_markdown_images(self):
        rendered_markdown, _ = build_rendered_markdown(
            "![이미지](https://attachment.hive-wiki.com/community-images/tmp/example.png)"
        )

        self.assertIn("<img", rendered_markdown)
        self.assertIn(
            'src="https://attachment.hive-wiki.com/community-images/tmp/example.png"',
            rendered_markdown,
        )
        self.assertIn('alt="이미지"', rendered_markdown)

    def test_build_rendered_markdown_strips_unsafe_image_attributes(self):
        rendered_markdown, _ = build_rendered_markdown(
            '![이미지](https://attachment.hive-wiki.com/community-images/tmp/example.png){onclick="alert(1)"}'
        )

        self.assertIn("<img", rendered_markdown)
        self.assertNotIn("onclick=", rendered_markdown)
