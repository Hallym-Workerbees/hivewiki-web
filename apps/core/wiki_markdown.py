import re

from django.utils.text import slugify

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+\s*)?$")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
MARKDOWN_LINK_RE = re.compile(r"!?(\[([^\]]+)\]\([^)]+\))")
MARKDOWN_EMPHASIS_RE = re.compile(r"[*_~]+")


def build_markdown_context(
    markdown_text: str,
) -> tuple[str, list[dict[str, str | int]]]:
    if not markdown_text:
        return "", []

    seen_ids: dict[str, int] = {}
    processed_lines: list[str] = []
    toc_items: list[dict[str, str | int]] = []

    for line in markdown_text.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            processed_lines.append(line)
            continue

        hashes, raw_heading = match.groups()
        heading_text = _plain_heading_text(raw_heading).strip()
        heading_id = _unique_heading_id(heading_text, seen_ids)
        level = len(hashes)

        processed_lines.append(f"{hashes} {raw_heading} {{#{heading_id}}}")
        toc_items.append(
            {
                "level": level,
                "text": heading_text or raw_heading.strip(),
                "id": heading_id,
            }
        )

    return "\n".join(processed_lines), toc_items


def annotate_toc_items(
    toc_items: list[dict[str, str | int]],
) -> list[dict[str, str | int]]:
    if not toc_items:
        return []

    min_level = min(int(item["level"]) for item in toc_items)
    counters = [0] * 6
    annotated_items: list[dict[str, str | int]] = []

    for item in toc_items:
        normalized_level = int(item["level"]) - min_level + 1
        counters[normalized_level - 1] += 1
        for index in range(normalized_level, len(counters)):
            counters[index] = 0

        annotated_items.append(
            {
                **item,
                "toc_level": normalized_level,
                "label": _toc_label(normalized_level, counters[normalized_level - 1]),
            }
        )

    return annotated_items


def strip_leading_title_heading(markdown_text: str, title: str) -> str:
    if not markdown_text:
        return ""

    lines = markdown_text.splitlines()
    if not lines:
        return markdown_text

    first_line = lines[0].strip()
    match = HEADING_RE.match(first_line)
    if not match:
        return markdown_text

    hashes, raw_heading = match.groups()
    if len(hashes) != 1:
        return markdown_text

    heading_text = _plain_heading_text(raw_heading)
    if heading_text != title.strip():
        return markdown_text

    remaining_lines = lines[1:]
    while remaining_lines and not remaining_lines[0].strip():
        remaining_lines.pop(0)
    return "\n".join(remaining_lines)


def _plain_heading_text(value: str) -> str:
    plain_text = MARKDOWN_LINK_RE.sub(r"\2", value)
    plain_text = INLINE_CODE_RE.sub(r"\1", plain_text)
    plain_text = MARKDOWN_EMPHASIS_RE.sub("", plain_text)
    return plain_text.strip()


def _unique_heading_id(heading_text: str, seen_ids: dict[str, int]) -> str:
    base_id = slugify(heading_text, allow_unicode=True) or "section"
    count = seen_ids.get(base_id, 0)
    seen_ids[base_id] = count + 1
    if count == 0:
        return base_id
    return f"{base_id}-{count + 1}"


def _toc_label(level: int, index: int) -> str:
    if level == 1:
        return f"{index}."
    if level == 2:
        return f"{chr(96 + index)}."
    if level == 3:
        return f"{index})"
    if level == 4:
        return f"{chr(64 + index)})"
    return f"{index}."
