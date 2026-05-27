import re

import bleach
import markdown
from django.core.cache import cache

from apps.core.wiki_markdown import (
    annotate_toc_items,
    build_markdown_context,
    strip_leading_title_heading,
)

ALLOWED_TAGS = [
    "a",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
]
ALLOWED_ATTRIBUTES = {
    "*": ["class", "id"],
    "a": ["href", "title", "rel"],
    "div": ["class"],
    "span": ["class"],
    "code": ["class"],
    "pre": ["class"],
    "img": ["alt", "src", "title"],
    "input": ["checked", "disabled", "type"],
}
REVISION_RENDER_CACHE_TIMEOUT = 60 * 60 * 24 * 7
CODE_NODE_RE = re.compile(r"<code\b[^>]*>.*?</code>", re.DOTALL)
INLINE_SOURCE_RE = re.compile(r"출처:\s*\[([^\]]+)\]\(([^)\s]+)\)")


def build_rendered_markdown(
    markdown_text: str,
) -> tuple[str, list[dict[str, str | int]]]:
    if not markdown_text:
        return "", []

    processed_markdown, toc_items = build_markdown_context(markdown_text)
    rendered = markdown.markdown(
        processed_markdown,
        extensions=[
            "markdown.extensions.attr_list",
            "markdown.extensions.codehilite",
            "markdown.extensions.extra",
            "markdown.extensions.nl2br",
            "markdown.extensions.sane_lists",
            "pymdownx.arithmatex",
            "pymdownx.tasklist",
        ],
        extension_configs={
            "markdown.extensions.codehilite": {
                "guess_lang": False,
                "noclasses": False,
                "pygments_style": "monokai",
            },
            "pymdownx.arithmatex": {"generic": True},
            "pymdownx.tasklist": {"clickable_checkbox": False},
        },
        output_format="html5",
    )
    sanitized = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=False,
    )
    linked = bleach.linkify(
        sanitized,
        callbacks=[_set_link_rel],
        skip_tags=["pre", "code"],
        parse_email=False,
    )
    return _restore_code_entities(linked), annotate_toc_items(toc_items)


def get_cached_revision_render(*, revision, title: str) -> dict[str, object]:
    if revision is None:
        return {
            "citations": [],
            "display_markdown": "",
            "rendered_markdown": "",
            "toc_items": [],
        }

    cache_key = f"wiki_revision_render:{revision.pk}"
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value

    display_markdown = strip_leading_title_heading(revision.content_markdown, title)
    display_markdown, citations = _extract_inline_citations(display_markdown)
    rendered_markdown, toc_items = build_rendered_markdown(display_markdown)
    payload = {
        "citations": citations,
        "display_markdown": display_markdown,
        "rendered_markdown": rendered_markdown,
        "toc_items": toc_items,
    }
    cache.set(cache_key, payload, REVISION_RENDER_CACHE_TIMEOUT)
    return payload


def _set_link_rel(attrs, new=False):
    href_key = (None, "href")
    if href_key not in attrs:
        return attrs

    attrs[(None, "rel")] = "noopener noreferrer"
    return attrs


def _restore_code_entities(rendered_html: str) -> str:
    return CODE_NODE_RE.sub(_restore_code_node_entities, rendered_html)


def _restore_code_node_entities(match: re.Match[str]) -> str:
    code_html = match.group(0)
    return (
        code_html.replace("&amp;lt;", "&lt;")
        .replace("&amp;gt;", "&gt;")
        .replace("&amp;quot;", "&quot;")
        .replace("&amp;#39;", "&#39;")
        .replace("&amp;amp;", "&amp;")
    )


def _extract_inline_citations(
    markdown_text: str,
) -> tuple[str, list[dict[str, str | int]]]:
    if not markdown_text:
        return "", []

    citations: list[dict[str, str | int]] = []
    citation_numbers: dict[tuple[str, str], int] = {}

    def replace(match: re.Match[str]) -> str:
        title, url = match.groups()
        key = (title.strip(), url.strip())
        number = citation_numbers.get(key)
        if number is None:
            number = len(citations) + 1
            citation_numbers[key] = number
            citations.append(
                {
                    "index": number,
                    "title": key[0],
                    "url": key[1],
                }
            )
        return f'<sup class="wiki-citation-marker">[{number}]</sup>'

    cleaned_markdown = INLINE_SOURCE_RE.sub(replace, markdown_text)
    return cleaned_markdown, citations
