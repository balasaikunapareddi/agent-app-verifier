"""Renderer: turns a spec + live state into HTML and a PNG "screenshot".

Two views of the same UI tree, computed from one layout pass:

- :func:`compute_layout` — deterministic bounding boxes for every component.
- :func:`render_html` — a real page served by :mod:`agent_app_verifier.cli`
  on ``http://127.0.0.1:<port>/`` (stdlib ``http.server`` only).
- :func:`render_png` — draws the same tree with PIL. This PNG is what the
  agent "sees" through the driver's ``screenshot`` operation. It is a render
  of the UI tree, not a capture from a real browser — see the README's
  honest-limits section.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .spec import AppSpec, render_template

CANVAS_WIDTH = 480
PAD = 24
GAP = 12
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

LIGHT = {
    "bg": (250, 250, 248), "surface": (255, 255, 255), "text": (24, 24, 24),
    "muted": (110, 110, 110), "border": (210, 210, 205),
    "accent": (37, 99, 235), "accent_text": (255, 255, 255),
    "done": (150, 150, 145), "danger": (190, 40, 40),
}
DARK = {
    "bg": (24, 26, 32), "surface": (38, 41, 51), "text": (235, 235, 230),
    "muted": (150, 152, 160), "border": (70, 74, 86),
    "accent": (96, 140, 250), "accent_text": (255, 255, 255),
    "done": (120, 122, 130), "danger": (240, 110, 110),
}

# Fixed heights per component type (px). Deterministic on purpose: the
# layout the agent reads is the layout that is drawn.
HEIGHTS = {"text": 30, "timer": 30, "input": 46, "button": 46, "list_item": 42}


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.w, "height": self.h}


def compute_layout(spec: AppSpec, state: dict) -> dict[str, Box]:
    """Deterministic boxes for every component (and list item)."""
    boxes: dict[str, Box] = {}
    y = PAD
    width = CANVAS_WIDTH - 2 * PAD
    for comp in spec.components:
        if comp.type == "list":
            items = state.get(comp.source, [])
            boxes[comp.id] = Box(PAD, y, width, max(1, len(items)) * HEIGHTS["list_item"])
            for i in range(len(items)):
                boxes[f"{comp.id}:{i}"] = Box(
                    PAD, y + i * HEIGHTS["list_item"], width, HEIGHTS["list_item"])
            y += max(1, len(items)) * HEIGHTS["list_item"] + GAP
        else:
            h = HEIGHTS[comp.type]
            boxes[comp.id] = Box(PAD, y, width, h)
            y += h + GAP
    return boxes


def display_text(spec: AppSpec, comp_id: str, state: dict, inputs: dict) -> str:
    """The text a component currently shows (templates resolved)."""
    comp = spec.component(comp_id)
    context = dict(state)
    context["remaining"] = sum(1 for t in state.get("todos", []) if not t.get("done"))
    context["count"] = len(state.get("todos", []))
    context["elapsed"] = int(state.get("clock", 0)) - int(state.get("last_updated", 0))
    context.update({f"input:{k}": v for k, v in inputs.items()})
    if comp.type == "timer":
        return render_template(comp.template or comp.text, context)
    if comp.template:
        return render_template(comp.template, context)
    return comp.text


def _fonts(size: int = 16, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def render_png(spec: AppSpec, state: dict, inputs: dict, theme: str,
               out_path: str | Path) -> dict[str, object]:
    """Draw the current UI as a PNG. Returns {path, width, height}."""
    palette = DARK if theme == "dark" else LIGHT
    layout = compute_layout(spec, state)
    height = max((b.y + b.h for b in layout.values()), default=PAD) + PAD
    img = Image.new("RGB", (CANVAS_WIDTH, height), palette["bg"])
    draw = ImageDraw.Draw(img)

    for comp in spec.components:
        box = layout[comp.id]
        if comp.type == "text":
            draw.text((box.x, box.y + 4), display_text(spec, comp.id, state, inputs),
                      font=_fonts(18, bold=True), fill=palette["text"])
        elif comp.type == "timer":
            draw.text((box.x, box.y + 4), display_text(spec, comp.id, state, inputs),
                      font=_fonts(13), fill=palette["muted"])
        elif comp.type == "input":
            draw.rounded_rectangle(
                [box.x, box.y, box.x + box.w, box.y + box.h], radius=8,
                fill=palette["surface"], outline=palette["border"], width=1)
            value = inputs.get(comp.id, "")
            shown = value if value else comp.placeholder
            color = palette["text"] if value else palette["muted"]
            draw.text((box.x + 12, box.y + 13), shown, font=_fonts(15), fill=color)
        elif comp.type == "button":
            draw.rounded_rectangle(
                [box.x, box.y, box.x + box.w, box.y + box.h], radius=8,
                fill=palette["accent"])
            label = comp.label
            tw = draw.textlength(label, font=_fonts(15, bold=True))
            draw.text((box.x + (box.w - tw) / 2, box.y + 13), label,
                      font=_fonts(15, bold=True), fill=palette["accent_text"])
        elif comp.type == "list":
            items = state.get(comp.source, [])
            if not items:
                draw.text((box.x, box.y + 10), "No todos yet — add one above.",
                          font=_fonts(14), fill=palette["muted"])
            for i, item in enumerate(items):
                ibox = layout[f"{comp.id}:{i}"]
                cy = ibox.y + ibox.h // 2
                # checkbox
                draw.rounded_rectangle(
                    [ibox.x, cy - 10, ibox.x + 20, cy + 10], radius=4,
                    outline=palette["border"], width=2,
                    fill=palette["accent"] if item.get("done") else palette["surface"])
                if item.get("done"):
                    draw.text((ibox.x + 4, cy - 10), "✓", font=_fonts(14, bold=True),
                              fill=palette["accent_text"])
                text = str(item.get("text", ""))
                color = palette["done"] if item.get("done") else palette["text"]
                draw.text((ibox.x + 32, cy - 9), text, font=_fonts(15), fill=color)
                # delete "x" on the right
                draw.text((ibox.x + ibox.w - 22, cy - 10), "✕", font=_fonts(14),
                          fill=palette["danger"])
                if i < len(items) - 1:
                    draw.line([ibox.x, ibox.y + ibox.h, ibox.x + ibox.w, ibox.y + ibox.h],
                              fill=palette["border"], width=1)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return {"path": str(out), "width": CANVAS_WIDTH, "height": height, "format": "PNG"}


def render_html(spec: AppSpec, state: dict, inputs: dict, theme: str) -> str:
    """A real, servable page for the same UI tree."""
    palette = DARK if theme == "dark" else LIGHT
    css_vars = (
        f"--bg: rgb{palette['bg']}; --surface: rgb{palette['surface']}; "
        f"--text: rgb{palette['text']}; --muted: rgb{palette['muted']}; "
        f"--border: rgb{palette['border']}; --accent: rgb{palette['accent']}; "
        f"--accent-text: rgb{palette['accent_text']}; --danger: rgb{palette['danger']};"
    )
    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(spec.title)}</title>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<style>",
        f":root {{{css_vars}}}",
        "body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; "
        "margin: 0; padding: 24px; }",
        ".app { max-width: 432px; margin: 0 auto; }",
        "h1 { font-size: 22px; margin: 0 0 12px; }",
        ".timer { color: var(--muted); font-size: 13px; margin: 0 0 12px; }",
        "input[type=text] { width: 100%; box-sizing: border-box; padding: 12px; font-size: 15px; "
        "border: 1px solid var(--border); border-radius: 8px; background: var(--surface); "
        "color: var(--text); margin-bottom: 12px; }",
        "button.add { width: 100%; padding: 12px; font-size: 15px; font-weight: 700; "
        "border: 0; border-radius: 8px; background: var(--accent); color: var(--accent-text); "
        "cursor: pointer; margin-bottom: 12px; }",
        "ul { list-style: none; padding: 0; margin: 0 0 12px; }",
        "li { display: flex; align-items: center; gap: 10px; padding: 10px 0; "
        "border-bottom: 1px solid var(--border); }",
        "li.done span { color: var(--muted); text-decoration: line-through; }",
        "li .del { margin-left: auto; color: var(--danger); background: none; border: 0; "
        "font-size: 15px; cursor: pointer; }",
        ".remaining { font-size: 15px; }",
        ".empty { color: var(--muted); }",
        "</style></head><body><div class='app'>",
    ]
    for comp in spec.components:
        if comp.type == "text":
            if comp.id == "header":
                parts.append(f"<h1 data-testid='{comp.id}'>{html.escape(display_text(spec, comp.id, state, inputs))}</h1>")
            else:
                parts.append(f"<p class='remaining' data-testid='{comp.id}'>{html.escape(display_text(spec, comp.id, state, inputs))}</p>")
        elif comp.type == "timer":
            parts.append(f"<p class='timer' data-testid='{comp.id}'>{html.escape(display_text(spec, comp.id, state, inputs))}</p>")
        elif comp.type == "input":
            value = html.escape(inputs.get(comp.id, ""), quote=True)
            parts.append(
                f"<input type='text' data-testid='{comp.id}' value='{value}' "
                f"placeholder='{html.escape(comp.placeholder, quote=True)}'>")
        elif comp.type == "button":
            parts.append(f"<button class='add' data-testid='{comp.id}'>{html.escape(comp.label)}</button>")
        elif comp.type == "list":
            items = state.get(comp.source, [])
            if not items:
                parts.append("<p class='empty'>No todos yet — add one above.</p>")
            else:
                parts.append(f"<ul data-testid='{comp.id}'>")
                for i, item in enumerate(items):
                    cls = " class='done'" if item.get("done") else ""
                    checked = " checked" if item.get("done") else ""
                    parts.append(
                        f"<li{cls} data-testid='{comp.id}:{i}'>"
                        f"<input type='checkbox'{checked} data-testid='{comp.id}:{i}:toggle'>"
                        f"<span>{html.escape(str(item.get('text', '')))}</span>"
                        f"<button class='del' data-testid='{comp.id}:{i}:delete'>✕</button></li>")
                parts.append("</ul>")
    parts.append("</div></body></html>")
    return "".join(parts)
