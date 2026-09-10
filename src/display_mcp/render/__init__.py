"""Renderer: draws a display list the way firmware/display_list.h does.

Port of epaper-display/server/dlpreview.py. The C++ in the firmware is
authoritative; where they differ, this is the bug — except for the three
deliberate fixes called out in docs/PLAN.md ("Renderer"):

1. ``weather-snowy`` is a valid, compiled-in icon (dlpreview.py was missing
   it). A procedural stand-in is drawn for it like the other weather icons.
2. Icons are validated as ``name/z`` pairs, the way the firmware keys its
   compiled icon table (``assets.icons["check/sm"]`` etc.) — an icon whose
   size class was never compiled in is now a problem, not a silent pass.
3. The off-canvas check also covers ``x+w``/``y+h`` for rects and
   ``x2``/``y2`` for lines, with the same +/-64px tolerance already applied
   to every op's ``x``/``y``.

Public surface (final):
    WIDTH, HEIGHT            1200, 1600
    FONTS                    {name: (size, bold)} for xl lg md sm xs
    ICONS                    {name: frozenset(size classes)} e.g. {"check": {"sm"}}
    ICON_SIZES               {size class: pixel size}
    COLORS                   the six ink names
    render_hash(doc) -> str  sha256 of canonical {bg, palette, ops}, first 16 hex
    render(doc, font_dir, ideal=False) -> (PIL.Image.Image, list[str])
    check(doc, font_dir) -> list[str]   problems only, no image
    fit_line(font, s, max_w) / wrap_lines(font, s, max_w, max_lines)
    fonts_available(font_dir) -> bool
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 1600

COLORS = ("black", "white", "yellow", "red", "blue", "green")

# name -> (size px, bold). Compiled into the firmware; changing one is a rebuild.
FONTS: dict[str, tuple[int, bool]] = {
    "xl": (84, True),
    "lg": (48, True),
    "md": (36, False),
    "sm": (28, False),
    "xs": (22, True),
}

# name -> size classes the firmware compiled. Keyed "name/z" on the panel.
ICONS: dict[str, frozenset[str]] = {
    "weather-sunny": frozenset({"lg"}),
    "weather-partly-cloudy": frozenset({"lg"}),
    "weather-cloudy": frozenset({"lg"}),
    "weather-rainy": frozenset({"lg"}),
    "weather-snowy": frozenset({"lg"}),
    "weather-night": frozenset({"lg"}),
    "check": frozenset({"sm"}),
    "map-marker": frozenset({"sm"}),
    "clock": frozenset({"sm"}),
    "alert": frozenset({"sm"}),
    "battery": frozenset({"sm"}),
}

ICON_SIZES = {"sm": 36, "md": 56, "lg": 88}

# The panel sits behind a printed bezel (mount/epaper_frame_bezel.scad)
# whose window is the active area less 1 mm per edge: ~6 px hidden, plus a
# couple of pixels of panel float and the shadow of the 45° bevel. Text and
# icons whose anchor lands inside this band are flagged by check(); fills and
# bars are meant to run full bleed and are not.
BEZEL_MARGIN = 24

# What the driver writes into the framebuffer.
IDEAL = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}

# Roughly what those inks look like on a Spectra 6 panel.
INK = {
    "black": (32, 32, 32),
    "white": (222, 222, 216),
    "yellow": (206, 172, 44),
    "red": (156, 46, 42),
    "blue": (46, 62, 128),
    "green": (72, 108, 66),
}

ANCHOR = {"left": "la", "center": "ma", "right": "ra"}

_NO_HASH_WARNING = (
    "no meta.hash — the panel will refresh on EVERY wake "
    "(~36 mAh/day, roughly half its battery life). Run with --stamp."
)


def _font_path(font_dir: Path, bold: bool) -> Path:
    name = "InstrumentSans-Bold.ttf" if bold else "InstrumentSans-Regular.ttf"
    return Path(font_dir) / name


def load_font(font_dir: Path, size: int, bold: bool) -> ImageFont.FreeTypeFont:
    """Load one face. `bold` also selects the variable font's "Bold" instance.

    Google Fonts ships Instrument Sans as a variable font: Pillow loads the
    default instance (Regular) unless the named instance is selected, and
    the wrong weight means text wraps in different places than the panel
    does. A static Bold face (nothing to select) is fine too.
    """
    f = ImageFont.truetype(str(_font_path(font_dir, bold)), size)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass  # a static Bold face: nothing to select
    return f


def _load_fonts(font_dir: Path) -> dict[str, ImageFont.FreeTypeFont]:
    return {name: load_font(font_dir, size, bold) for name, (size, bold) in FONTS.items()}


def fonts_available(font_dir: Path) -> bool:
    font_dir = Path(font_dir)
    return (font_dir / "InstrumentSans-Regular.ttf").exists() and (
        font_dir / "InstrumentSans-Bold.ttf"
    ).exists()


class Ctx:
    def __init__(self, doc: dict[str, Any], font_dir: Path, ideal: bool = False):
        self.palette = doc.get("palette") or {}
        self.table = IDEAL if ideal else INK
        self.fonts = _load_fonts(Path(font_dir))
        self.problems: list[str] = []

    def color(self, name: str, where: str = ""):
        # Palette aliases resolve up to 8 hops, matching resolve_color() in
        # display_list.h; a cycle (or a chain deeper than that) falls back
        # to black with a problem instead of hanging.
        n = name
        for _ in range(8):
            if n in self.table:
                return self.table[n]
            nxt = self.palette.get(n)
            if nxt is None:
                break
            n = nxt
        self.problems.append(f"{where}: unknown colour {n!r}")
        return self.table["black"]

    def font(self, name: str, where: str = ""):
        if name not in self.fonts:
            self.problems.append(f"{where}: unknown font {name!r}")
            return self.fonts["md"]
        return self.fonts[name]


def text_width(font, s: str) -> int:
    return font.getbbox(s)[2] - font.getbbox(s)[0]


def fit_line(font, s: str, max_w):
    """Truncate to max_w with an ellipsis. Mirrors dl_fit_line() in the header."""
    if max_w is None or text_width(font, s) <= max_w:
        return s
    ell = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(font, s[:mid] + ell) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + ell


def wrap_lines(font, s: str, max_w, max_lines: int):
    """Greedy word wrap; last line ellipsized if it overflows. Mirrors dl_wrap()."""
    words = s.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(font, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines:
        used = sum(len(line.split()) for line in lines)
        if used < len(words):
            lines[-1] = fit_line(font, lines[-1] + " " + words[used], max_w)
    # A single word longer than the box would otherwise escape unclipped.
    return [fit_line(font, line, max_w) for line in lines[:max_lines]]


def draw_icon(d: ImageDraw.ImageDraw, name: str, x, y, size, fill):
    """Procedural stand-ins. The panel draws real MDI bitmaps."""
    s = size
    cx, cy = x + s / 2, y + s / 2
    lw = max(2, round(s * 0.09))

    def sun(scale=1.0, ox=0.0, oy=0.0):
        r = s * 0.19 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - r, py - r, px + r, py + r], fill=fill)
        for i in range(8):
            a = i * math.pi / 4
            d.line(
                [
                    px + math.cos(a) * r * 1.5,
                    py + math.sin(a) * r * 1.5,
                    px + math.cos(a) * r * 2.2,
                    py + math.sin(a) * r * 2.2,
                ],
                fill=fill,
                width=lw,
            )

    def cloud(ox=0.0, oy=0.0, scale=1.0):
        w = s * 0.72 * scale
        h = s * 0.42 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - w / 2, py - h / 2, px - w / 2 + h, py + h / 2], fill=fill)
        d.ellipse([px + w / 2 - h, py - h / 2, px + w / 2, py + h / 2], fill=fill)
        d.rectangle([px - w / 2 + h / 2, py - h / 2, px + w / 2 - h / 2, py + h / 2], fill=fill)
        d.ellipse([px - w * 0.18, py - h * 0.95, px + w * 0.34, py + h * 0.35], fill=fill)

    if name == "weather-sunny":
        sun(1.25)
    elif name == "weather-partly-cloudy":
        sun(0.8, ox=0.16, oy=-0.20)
        cloud(ox=-0.04, oy=0.12, scale=0.95)
    elif name == "weather-cloudy":
        cloud(oy=0.02, scale=1.1)
    elif name == "weather-rainy":
        cloud(oy=-0.10, scale=1.0)
        for i in range(3):
            rx = cx + (i - 1) * s * 0.22
            d.line([rx, cy + s * 0.20, rx - s * 0.06, cy + s * 0.40], fill=fill, width=lw)
    elif name == "weather-snowy":
        # Same cloud as the other weather glyphs, with a few flake dots
        # instead of rain's diagonal streaks.
        cloud(oy=-0.10, scale=1.0)
        for i in range(3):
            fx = cx + (i - 1) * s * 0.24
            fy = cy + s * 0.30 + (i % 2) * s * 0.10
            rr = max(1.8, s * 0.05)
            d.ellipse([fx - rr, fy - rr, fx + rr, fy + rr], fill=fill)
    elif name == "weather-night":
        r = s * 0.30
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        box = [cx - r * 0.45, cy - r * 1.30, cx + r * 1.65, cy + r * 0.60]
        d.ellipse(box, fill=None)
        d.pieslice(box, 0, 360, fill=(0, 0, 0, 0))
    elif name == "map-marker":
        r = s * 0.26
        top = y + s * 0.14
        d.ellipse([cx - r, top, cx + r, top + 2 * r], fill=fill)
        d.polygon(
            [
                (cx - r * 0.78, top + r * 1.35),
                (cx + r * 0.78, top + r * 1.35),
                (cx, y + s * 0.92),
            ],
            fill=fill,
        )
        hr = r * 0.38
        d.ellipse([cx - hr, top + r - hr, cx + hr, top + r + hr], fill=(255, 255, 255))
    elif name == "check":
        d.line([x + s * 0.20, y + s * 0.52, x + s * 0.42, y + s * 0.74], fill=fill, width=lw + 1)
        d.line([x + s * 0.42, y + s * 0.74, x + s * 0.80, y + s * 0.28], fill=fill, width=lw + 1)
    elif name == "clock":
        r = s * 0.36
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=lw)
        d.line([cx, cy, cx, cy - r * 0.55], fill=fill, width=lw)
        d.line([cx, cy, cx + r * 0.45, cy], fill=fill, width=lw)
    elif name == "alert":
        d.polygon(
            [(cx, y + s * 0.14), (x + s * 0.92, y + s * 0.84), (x + s * 0.08, y + s * 0.84)],
            fill=fill,
        )
        d.line([cx, y + s * 0.38, cx, y + s * 0.62], fill=(255, 255, 255), width=lw)
        d.ellipse(
            [cx - lw * 0.7, y + s * 0.68, cx + lw * 0.7, y + s * 0.68 + lw * 1.4],
            fill=(255, 255, 255),
        )
    elif name == "battery":
        bw, bh = s * 0.52, s * 0.76
        d.rectangle(
            [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], outline=fill, width=lw
        )
        d.rectangle(
            [cx - bw * 0.18, cy - bh / 2 - lw * 1.6, cx + bw * 0.18, cy - bh / 2], fill=fill
        )
        d.rectangle(
            [cx - bw / 2 + lw, cy - bh * 0.10, cx + bw / 2 - lw, cy + bh / 2 - lw], fill=fill
        )
    else:
        d.rectangle([x, y, x + s, y + s], outline=fill, width=lw)


def render_hash(doc: dict[str, Any]) -> str:
    """Identity of what the document DRAWS: bg + palette + ops, nothing else.

    Must stay byte-identical to `document_id()` in firmware/display_list.h;
    the panel compares its own reading of meta.hash against what we stamp.
    samples/display.json hashes to 21a77f4c46f1534d.
    """
    core = {k: doc.get(k) for k in ("bg", "palette", "ops")}
    canon = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


TONES = ("light",)

FIELD_RE = re.compile(r"\{([a-z0-9_]+)\}")


def system_fields(doc: dict[str, Any], now: datetime | None = None) -> dict[str, str]:
    """Values the `fmt` op can print. The firmware fills the same names.

    {hash}/{hash16} come from render_hash(doc), which equals meta.hash for a
    correctly stamped document. {time}/{time24} are the moment of drawing:
    here the preview's clock, on the panel its own SNTP-synced clock.
    {battery}/{battv} are the panel's ADC reading; stand-ins here.
    """
    h = render_hash(doc)
    t = now or datetime.now()
    hour12 = t.hour % 12 or 12
    return {
        "hash": h[-5:],
        "hash16": h,
        "time": f"{hour12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}",
        "time24": f"{t.hour:02d}:{t.minute:02d}",
        # The panel fills these from its ADC; the preview has no battery, so
        # it shows a stand-in that is obviously plausible rather than blank.
        "battery": "82%",
        "battv": "3.9V",
    }


def expand_fields(template: str, fields: dict[str, str]) -> tuple[str, list[str]]:
    """Substitute {field}s; unknown ones stay literal and are reported."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in fields:
            return fields[name]
        unknown.append(name)
        return m.group(0)

    return FIELD_RE.sub(sub, template), unknown


def _apply_tone_box(img, ctx, op, where, doc, x0, y0, x1, y1) -> None:
    """The checkerboard itself, over one box. Shared by text, fmt and icon."""
    tone = op.get("tone")
    if tone is None:
        return
    if tone not in TONES:
        ctx.problems.append(f"{where}: unknown tone {tone!r} (drawn at full ink)")
        return
    bg = ctx.color(op.get("bgc", doc.get("bg", "white")), where)
    px = img.load()
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(WIDTH, int(x1)), min(HEIGHT, int(y1))
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            if (xx + yy) % 2 == 0:
                px[xx, yy] = bg


def _apply_tone(img, d, ctx, op, where, drawn, font, anchor, doc) -> None:
    """tone: "light" — clear every other pixel of the drawn text's box to the
    background, which reads as a lighter tone on a six-ink panel that has no
    grey. `bgc` names what is underneath; default is the document bg, so
    text on a filled rect must set bgc or it gets speckled with bg.
    Mirrors lighten_box() in display_list.h.
    """
    if op.get("tone") is None:
        return
    for x, y, text in drawn:
        if not text:
            continue
        x0, y0, x1, y1 = d.textbbox((x, y), text, font=font, anchor=anchor)
        _apply_tone_box(img, ctx, op, where, doc, x0, y0, x1 + 1, y1 + 1)


def render(doc: dict[str, Any], font_dir: Path, ideal: bool = False, now: datetime | None = None):
    """Return (PIL image, problems). Never raises on a bad op; it reports it."""
    ctx = Ctx(doc, font_dir, ideal)
    img = Image.new("RGB", (WIDTH, HEIGHT), ctx.color(doc.get("bg", "white"), "bg"))
    d = ImageDraw.Draw(img)

    fields = system_fields(doc, now)

    for i, op in enumerate(doc.get("ops", [])):
        where = f"ops[{i}] {op.get('op', '?')}"
        kind = op.get("op")
        c = ctx.color(op.get("c", "black"), where)

        if kind == "rect":
            x, y, w, h = op["x"], op["y"], op["w"], op["h"]
            if op.get("fill", True):
                d.rectangle([x, y, x + w - 1, y + h - 1], fill=c)
            else:
                t = op.get("t", 1)
                d.rectangle([x, y, x + w - 1, y + h - 1], outline=c, width=t)
            xr, yr = x + w, y + h
            if not (-64 <= xr <= WIDTH + 64):
                ctx.problems.append(f"{where}: x+w={xr} is off-canvas")
            if not (-64 <= yr <= HEIGHT + 64):
                ctx.problems.append(f"{where}: y+h={yr} is off-canvas")

        elif kind == "line":
            t = op.get("t", 1)
            d.line([op["x"], op["y"], op["x2"], op["y2"]], fill=c, width=t)
            x2, y2 = op.get("x2"), op.get("y2")
            if isinstance(x2, (int, float)) and not (-64 <= x2 <= WIDTH + 64):
                ctx.problems.append(f"{where}: x2={x2} is off-canvas")
            if isinstance(y2, (int, float)) and not (-64 <= y2 <= HEIGHT + 64):
                ctx.problems.append(f"{where}: y2={y2} is off-canvas")

        elif kind == "circle":
            x, y, r = op["x"], op["y"], op["r"]
            box = [x - r, y - r, x + r, y + r]
            if op.get("fill", True):
                d.ellipse(box, fill=c)
            else:
                d.ellipse(box, outline=c, width=op.get("t", 1))

        elif kind == "text":
            f = ctx.font(op.get("f", "md"), where)
            anchor = ANCHOR.get(op.get("a", "left"), "la")
            max_w = op.get("w")
            if op.get("wrap"):
                lines = wrap_lines(f, op["s"], max_w, op.get("lines", 2))
                fname = op.get("f", "md")
                size = FONTS.get(fname, FONTS["md"])[0]
                lh = op.get("lh", round(size * 1.24))
                drawn = []
                for n, line in enumerate(lines):
                    d.text((op["x"], op["y"] + n * lh), line, font=f, fill=c, anchor=anchor)
                    drawn.append((op["x"], op["y"] + n * lh, line))
                _apply_tone(img, d, ctx, op, where, drawn, f, anchor, doc)
            else:
                text = fit_line(f, op["s"], max_w)
                d.text((op["x"], op["y"]), text, font=f, fill=c, anchor=anchor)
                _apply_tone(img, d, ctx, op, where, [(op["x"], op["y"], text)], f, anchor, doc)

        elif kind == "fmt":
            # text without wrap whose `s` is a template of system fields. The
            # values are never in the document, so meta.hash covers where and
            # how the line is drawn, never what it says.
            f = ctx.font(op.get("f", "xs"), where)
            anchor = ANCHOR.get(op.get("a", "left"), "la")
            text, unknown = expand_fields(op.get("s", ""), fields)
            for name in unknown:
                ctx.problems.append(f"{where}: unknown field {{{name}}} (left literal)")
            d.text((op["x"], op["y"]), text, font=f, fill=c, anchor=anchor)
            _apply_tone(img, d, ctx, op, where, [(op["x"], op["y"], text)], f, anchor, doc)

        elif kind == "icon":
            name = op.get("n")
            z = op.get("z", "sm")
            key = f"{name}/{z}"
            if name not in ICONS or z not in ICONS[name]:
                ctx.problems.append(f"{where}: {key!r} is not compiled in")
            size = ICON_SIZES.get(z, 36)
            draw_icon(d, name, op["x"], op["y"], size, c)
            x, y = op["x"], op["y"]
            _apply_tone_box(img, ctx, op, where, doc, x, y, x + size, y + size)

        else:
            ctx.problems.append(f"{where}: unknown op {kind!r}")

        for k in ("x", "y"):
            v = op.get(k)
            bound = WIDTH if k == "x" else HEIGHT
            if isinstance(v, (int, float)) and not (-64 <= v <= bound + 64):
                ctx.problems.append(f"{where}: {k}={v} is off-canvas")

    return img, ctx.problems


def bezel_problems(doc: dict[str, Any]) -> list[str]:
    """Text, fmt and icon ops whose anchor sits inside the bezel margin.

    Only the anchor corner is judged (plus the right edge of right-aligned
    text and of icons, whose extent is known): glyph boxes carry their own
    padding, so measuring the far edge would flag the standard footer.
    """
    out: list[str] = []
    for i, op in enumerate(doc.get("ops") or []):
        kind = op.get("op")
        if kind not in ("text", "fmt", "icon"):
            continue
        x, y = op.get("x"), op.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        where = f"ops[{i}] {kind}"
        edges: list[str] = []
        right_aligned = kind != "icon" and op.get("a") == "right"
        if right_aligned:
            if x > WIDTH - BEZEL_MARGIN:
                edges.append("right")
        elif x < BEZEL_MARGIN:
            edges.append("left")
        if kind == "icon" and x + ICON_SIZES.get(op.get("z"), 0) > WIDTH - BEZEL_MARGIN:
            edges.append("right")
        if y < BEZEL_MARGIN:
            edges.append("top")
        if kind != "icon":
            size = FONTS.get(op.get("f", "md" if kind == "text" else "xs"), FONTS["md"])[0]
            if y + size > HEIGHT - BEZEL_MARGIN:
                edges.append("bottom")
        if edges:
            out.append(
                f"{where}: within {BEZEL_MARGIN} px of the {' and '.join(edges)} edge, "
                "under or shadowed by the bezel"
            )
    return out


def check(doc: dict[str, Any], font_dir: Path) -> list[str]:
    """Problems only. Same validation as render(), plus the bezel margin and hash-staleness.

    One deliberate asymmetry about meta.hash: a *missing* hash is never
    reported. Store.publish() (docs/PLAN.md) is the only thing that stamps
    it, so a draft passed to check()/validate() legitimately carries none
    yet — not worth surfacing to a library caller. A *present but stale*
    hash (a copy-pasted older document, or hand editing after `stamp`) is
    still flagged: that one means the document on disk no longer draws what
    its hash claims, which the panel would act on.
    """
    _, problems = render(doc, font_dir)
    problems = problems + bezel_problems(doc)
    stamped = (doc.get("meta") or {}).get("hash")
    if stamped:
        h = render_hash(doc)
        if stamped != h:
            problems = [f"meta.hash is stale ({stamped}) — re-run with --stamp"] + problems
    return problems
