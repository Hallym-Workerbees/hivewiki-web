import re

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+\s*)?$")
MARKDOWN_LINK_RE = re.compile(r"!?(\[([^\]]+)\]\([^)]+\))")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
MARKDOWN_DECORATION_RE = re.compile(r"[*_~>#-]+")
MULTISPACE_RE = re.compile(r"\s+")
WIKI_LINK_RE = re.compile(r"/wiki/(?P<slug>[-\w]+)/")


def build_post_markdown(body_markdown: str) -> str:
    cleaned_body = body_markdown.strip()
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
    _, body_markdown = extract_post_title_and_body(content_markdown)
    source_text = body_markdown or content_markdown
    plain_text = _normalize_line(_plain_text(source_text))
    if len(plain_text) <= max_length:
        return plain_text
    return plain_text[: max_length - 1].rstrip() + "…"


def _plain_text(value: str) -> str:
    text = MARKDOWN_LINK_RE.sub(r"\2", value)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = MARKDOWN_DECORATION_RE.sub(" ", text)
    return MULTISPACE_RE.sub(" ", text).strip()


def _normalize_line(value: str) -> str:
    return MULTISPACE_RE.sub(" ", value.strip())
