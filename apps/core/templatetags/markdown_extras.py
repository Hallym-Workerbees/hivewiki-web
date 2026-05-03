import bleach
import markdown
from bleach.css_sanitizer import CSSSanitizer
from django import template
from django.utils.safestring import mark_safe

from apps.core.wiki_markdown import build_markdown_context

register = template.Library()

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
    "a": ["href", "title"],
    "div": ["class", "style"],
    "span": ["class", "style"],
    "code": ["class", "style"],
    "pre": ["class", "style"],
    "input": ["checked", "disabled", "type"],
}
CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "background-color",
        "color",
        "display",
        "font-style",
        "font-weight",
        "margin",
        "padding-left",
        "text-decoration",
    ]
)


@register.filter
def render_markdown(value):
    if not value:
        return ""

    processed_markdown, _ = build_markdown_context(value)
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
                "noclasses": True,
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
        css_sanitizer=CSS_SANITIZER,
        strip=True,
    )
    return mark_safe(sanitized)
