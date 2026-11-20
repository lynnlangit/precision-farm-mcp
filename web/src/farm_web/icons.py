"""A few small line icons, drawn here as inline SVG (no icon library, so the
app stays offline). Each is a 24x24 outline in the text's own colour, so it
follows the green / blue labels and dark mode without any extra CSS.

Used only where an icon carries meaning: the green "Calculated from your
records" and blue "Added by the AI, then checked" labels, the two folded
panels, and the five example question types. Always aria-hidden: the words
next to each icon say the same thing.
"""

from __future__ import annotations

from urllib.parse import quote

# name -> the SVG's inner paths (stroke only, no fill).
ICON_PATHS: dict[str, str] = {
    # A calculator: math done by code, from the records.
    "calculator": (
        '<rect x="5" y="2.5" width="14" height="19" rx="2"/>'
        '<path d="M8.5 6.5h7M8.5 11h.01M12 11h.01M15.5 11h.01'
        'M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h7"/>'
    ),
    # A sparkle (the AI) with a check mark beside it (then checked).
    "ai-checked": (
        '<path d="M9 2l1.9 4.6L15.5 8.5l-4.6 1.9L9 15l-1.9-4.6L2.5 8.5l4.6-1.9z"/>'
        '<path d="M13 18l3 3 6-6"/>'
    ),
    # A shield with a check: the checks the AI's sentence must pass.
    "shield-check": (
        '<path d="M12 3l7 3v5c0 4.6-3 8.3-7 10-4-1.7-7-5.4-7-10V6z"/>'
        '<path d="M9 12l2.2 2.2L15.5 10"/>'
    ),
    # A small table: the raw figures.
    "table": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M3 15h18M9.5 4v16"/>',
    # A seedling in the ground: one field.
    "field": (
        '<path d="M3 21h18M12 21v-9"/>'
        '<path d="M12 12c0-4.2 2.8-6.5 7-6.5 0 4.2-2.8 6.5-7 6.5z"/>'
        '<path d="M12 14.5c0-3.3-2.3-5.5-6-5.5 0 3.3 2.3 5.5 6 5.5z"/>'
    ),
    # A dollar coin: money.
    "money": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M14.8 9.3c-.5-.9-1.5-1.4-2.8-1.4-1.6 0-2.8.8-2.8 2s1.2 1.7 2.8 2'
        ' 2.8.8 2.8 2-1.2 2-2.8 2c-1.3 0-2.4-.5-2.9-1.4M12 6v1.9M12 16.1V18"/>'
    ),
    # Two arrows passing each other: do two records agree?
    "agree": '<path d="M4 8h15l-3.5-3.5M20 16H5l3.5 3.5"/>',
    # A cloud with rain.
    "weather": (
        '<path d="M7 15.5a4 4 0 1 1 1-7.9 5 5 0 0 1 9.6 1.4A3.3 3.3 0 0 1 17 15.5z"/>'
        '<path d="M8.5 18.5l-1 2M12.5 18.5l-1 2M16.5 18.5l-1 2"/>'
    ),
    # A drop: what went on the field.
    "applied": (
        '<path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z"/>'
        '<path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5"/>'
    ),
}
# One small icon per question type, so the example list and the "What can I
# ask?" answer scan quickly. Keys are the headings in farm_host.examples.
EXAMPLE_ICONS: dict[str, str] = {
    "Bad field or bad year?": "field",
    "Which fields made money?": "money",
    "Do my records agree?": "agree",
    "Weather and soil": "weather",
    "What did I apply?": "applied",
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" class="pf-icon" viewBox="0 0 24 24" width="1em" height="1em" fill="none" '
    'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true" focusable="false">{paths}</svg>'
)


def icon_svg(name: str) -> str:
    """The icon as inline SVG, drawn in the surrounding text's colour."""
    return _SVG.format(color="currentColor", paths=ICON_PATHS[name])


def icon_mask_url(name: str) -> str:
    """The icon as a CSS url(), for a mask over currentColor (used where the
    label is plain text Gradio renders, so an <svg> can't go inside it)."""
    svg = _SVG.format(color="black", paths=ICON_PATHS[name])
    return f'url("data:image/svg+xml,{quote(svg)}")'


def label_icons_css(classes: dict[str, str]) -> str:
    """CSS that puts an icon before the label of each Gradio accordion with
    the given elem_class (class -> icon name)."""
    rules = [
        f".{cls} > .label-wrap > span:first-child::before {{"
        f" -webkit-mask-image: {icon_mask_url(name)}; mask-image: {icon_mask_url(name)}; }}"
        for cls, name in classes.items()
    ]
    return "\n".join(rules)
