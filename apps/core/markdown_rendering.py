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
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
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
    "input": ["checked", "disabled", "type"],
}
REVISION_RENDER_CACHE_TIMEOUT = 60 * 60 * 24 * 7


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
    return linked, annotate_toc_items(toc_items)


def get_cached_revision_render(*, revision, title: str) -> dict[str, object]:
    if revision is None:
        return {
            "display_markdown": "",
            "rendered_markdown": "",
            "toc_items": [],
        }

    cache_key = f"wiki_revision_render:{revision.pk}"
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value

    display_markdown = strip_leading_title_heading(revision.content_markdown, title)
    rendered_markdown, toc_items = build_rendered_markdown(display_markdown)
    payload = {
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
