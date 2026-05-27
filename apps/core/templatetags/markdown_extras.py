from django import template
from django.utils.safestring import mark_safe

from apps.core.markdown_rendering import build_rendered_markdown

register = template.Library()


@register.filter
def render_markdown(value):
    if not value:
        return ""

    rendered_markdown, _ = build_rendered_markdown(value)
    return mark_safe(rendered_markdown)
