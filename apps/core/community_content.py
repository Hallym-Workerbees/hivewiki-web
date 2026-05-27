import html
import re

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+\s*)?$")
MARKDOWN_LINK_RE = re.compile(r"!?(\[([^\]]+)\]\([^)]+\))")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
MARKDOWN_DECORATION_RE = re.compile(r"[*_~>#-]+")
MULTISPACE_RE = re.compile(r"\s+")
WIKI_LINK_RE = re.compile(r"/wiki/(?P<slug>[-\w]+)/")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_ATTR_RE = re.compile(r'(?P<name>[\w:-]+)\s*=\s*"(?P<value>[^"]*)"')


def build_post_markdown(body_markdown: str) -> str:
    cleaned_body = _normalize_html_images(body_markdown).strip()
    if not cleaned_body:
        raise ValueError("게시글 본문은 비어 있을 수 없습니다.")
    return cleaned_body


def extract_post_title_and_body(content_markdown: str) -> tuple[str, str]:
    if not content_markdown:
        return "", ""

    lines = content_markdown.splitlines()
    first_content_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_content_index is None:
        return "", ""

    first_line = lines[first_content_index].strip()
    heading_match = HEADING_RE.match(first_line)
    if heading_match and len(heading_match.group(1)) == 1:
        title = _plain_text(heading_match.group(2))
        body_lines = lines[first_content_index + 1 :]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        return title, "\n".join(body_lines).strip()

    title = _normalize_line(_plain_text(first_line))
    return title, content_markdown.strip()


def strip_post_leading_title(content_markdown: str) -> str:
    _, body_markdown = extract_post_title_and_body(content_markdown)
    return body_markdown or content_markdown.strip()


def extract_post_render_parts(
    content_markdown: str, *, excerpt_max_length: int = 180
) -> tuple[str, str, str]:
    title, body_markdown = extract_post_title_and_body(content_markdown)
    normalized_content = content_markdown.strip() if content_markdown else ""
    display_body = body_markdown or normalized_content
    plain_text = _normalize_line(_plain_text(display_body))
    if len(plain_text) <= excerpt_max_length:
        excerpt = plain_text
    else:
        excerpt = plain_text[: excerpt_max_length - 1].rstrip() + "…"
    return title, display_body, excerpt


def extract_linked_wiki_slugs(content_markdown: str) -> list[str]:
    if not content_markdown:
        return []

    seen_slugs: set[str] = set()
    ordered_slugs: list[str] = []
    for match in WIKI_LINK_RE.finditer(content_markdown):
        slug = match.group("slug")
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        ordered_slugs.append(slug)
    return ordered_slugs


def build_post_excerpt(content_markdown: str, *, max_length: int = 180) -> str:
    _, _, excerpt = extract_post_render_parts(
        content_markdown, excerpt_max_length=max_length
    )
    return excerpt


def extract_first_image_url(content_markdown: str) -> str:
    if not content_markdown:
        return ""

    match = MARKDOWN_IMAGE_RE.search(content_markdown)
    if match:
        return match.group("url").strip()

    html_match = HTML_IMAGE_RE.search(content_markdown)
    if not html_match:
        return ""

    attributes = _parse_html_attributes(html_match.group(0))
    return attributes.get("src", "").strip()


def _plain_text(value: str) -> str:
    text = MARKDOWN_LINK_RE.sub(r"\2", value)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = MARKDOWN_DECORATION_RE.sub(" ", text)
    return MULTISPACE_RE.sub(" ", text).strip()


def _normalize_line(value: str) -> str:
    return MULTISPACE_RE.sub(" ", value.strip())


def _normalize_html_images(value: str) -> str:
    if not value:
        return ""
    return HTML_IMAGE_RE.sub(_replace_html_image_with_markdown, value)


def _replace_html_image_with_markdown(match: re.Match[str]) -> str:
    attributes = _parse_html_attributes(match.group(0))
    src = attributes.get("src", "").strip()
    if not src:
        return ""
    alt = attributes.get("alt", "").strip()
    return f"![{alt}]({src})"


def _parse_html_attributes(tag: str) -> dict[str, str]:
    return {
        attr_match.group("name").lower(): html.unescape(attr_match.group("value"))
        for attr_match in HTML_ATTR_RE.finditer(tag)
    }
