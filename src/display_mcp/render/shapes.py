"""Shapes: the rounded rect (D10), the icon stencil, the poly scanline fill
and outline walk (D12), the device-safety limits (THICK_MAX, SPRITE_MAX_CELL,
MAX_COORD, TEXT_MAX_LEN, TEXT_MAX_LINES, SPRITE_MAX_COLS, SPRITE_MAX_ROWS,
SPRITE_MAX_PALETTE, POLY_MAX_PTS -- docs/plans/firmware-bounds.md D4/D6/D7/D8)
and the off-canvas check every op's bounding box goes through
(`OFF_CANVAS_TOLERANCE` itself lives in `canvas.py`, since it's a canvas
constant, not a shape one -- this module is just its one reader).

Every constant here is mirrored by the same name (FOO -> kFoo) in
firmware/display_list.h; tests/parity/test_limits_and_dispatch.py extracts
and diffs each one by name. Content past one of these bounds is skipped
with a warning on this side too -- CLAUDE.md's "warnings never block a
publish" rule is what makes skip-not-reject safe here, the same as on the
panel.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw

from .canvas import HEIGHT, OFF_CANVAS_TOLERANCE, WIDTH

if TYPE_CHECKING:
    from .colour import Ctx

THICK_MAX = 64


SPRITE_MAX_CELL = max(WIDTH, HEIGHT)


# D4: one coordinate/size bound for every op -- x, y, w, h, x2, y2, r, each
# poly point, and a sprite's pixel box. More than twice the canvas on either
# axis, so full-bleed overhang and the existing off-canvas *warning* are
# unaffected; the worst single op (a 4096x4096 fill) costs about 0.8s on the
# panel. Supersedes the old POLY_MAX_COORD (1 << 20), which existed only to
# keep the poly scanline's crossing arithmetic away from overflow -- trivially
# true at this much smaller value.
MAX_COORD = 4096


# D6: `text.s` / `fmt.s` (the template, before expansion) longer than this
# skips the op -- the quadratic fit_line()/wrap() cost this protects is
# ~7ms and a ~6KB word vector at the bound. TEXT_MAX_LINES bounds wrapped
# `lines` the way THICK_MAX bounds `t`: clamped, not skipped.
TEXT_MAX_LEN = 512
TEXT_MAX_LINES = 64


# D7: the grid a sprite can describe. Together with MAX_COORD on its pixel
# box, the ragged-row walk can never visit more than
# SPRITE_MAX_COLS * SPRITE_MAX_ROWS cells.
SPRITE_MAX_COLS = 1200
SPRITE_MAX_ROWS = 1600
SPRITE_MAX_PALETTE = 64


# D8: how many points a poly's `pts` can hold.
POLY_MAX_PTS = 1024


def _off_canvas(v: float, bound: int) -> bool:
    """Whether `v` sits outside `[0, bound)` by more than
    `OFF_CANVAS_TOLERANCE`."""
    return not (-OFF_CANVAS_TOLERANCE <= v <= bound + OFF_CANVAS_TOLERANCE)


def _icon_mask(name: str, size: int) -> Image.Image:
    """The glyph as a 1-bit `size x size` stencil: 1 wherever the ink goes.

    Every shape is drawn into this tile instead of onto the page, so no
    helper can paint outside the icon's box however PIL decides to cap a
    thick line or stroke an ellipse. Holes — the moon's crescent, the
    marker's eye, the bang in the alert triangle — are punched back to 0
    rather than painted white: the panel's icons are BINARY images drawn
    with `transparency: chroma_key`, so their off pixels are skipped, not
    filled with anything.
    """
    s = int(size)
    mask = Image.new("1", (s, s), 0)
    d = ImageDraw.Draw(mask)
    ON, OFF = 1, 0
    cx = cy = s / 2
    lw = max(2, round(s * 0.09))

    def sun(scale=1.0, ox=0.0, oy=0.0):
        r = s * 0.19 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - r, py - r, px + r, py + r], fill=ON)
        for i in range(8):
            a = i * math.pi / 4
            d.line(
                [
                    px + math.cos(a) * r * 1.5,
                    py + math.sin(a) * r * 1.5,
                    px + math.cos(a) * r * 2.2,
                    py + math.sin(a) * r * 2.2,
                ],
                fill=ON,
                width=lw,
            )

    def cloud(ox=0.0, oy=0.0, scale=1.0):
        w = s * 0.72 * scale
        h = s * 0.42 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - w / 2, py - h / 2, px - w / 2 + h, py + h / 2], fill=ON)
        d.ellipse([px + w / 2 - h, py - h / 2, px + w / 2, py + h / 2], fill=ON)
        d.rectangle([px - w / 2 + h / 2, py - h / 2, px + w / 2 - h / 2, py + h / 2], fill=ON)
        d.ellipse([px - w * 0.18, py - h * 0.95, px + w * 0.34, py + h * 0.35], fill=ON)

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
            d.line([rx, cy + s * 0.20, rx - s * 0.06, cy + s * 0.40], fill=ON, width=lw)
    elif name == "weather-snowy":
        # Same cloud as the other weather glyphs, with a few flake dots
        # instead of rain's diagonal streaks.
        cloud(oy=-0.10, scale=1.0)
        for i in range(3):
            fx = cx + (i - 1) * s * 0.24
            fy = cy + s * 0.30 + (i % 2) * s * 0.10
            rr = max(1.8, s * 0.05)
            d.ellipse([fx - rr, fy - rr, fx + rr, fy + rr], fill=ON)
    elif name == "weather-night":
        r = s * 0.30
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ON)
        # The crescent is the bite an offset disc takes out of that one.
        d.ellipse([cx - r * 0.45, cy - r * 1.30, cx + r * 1.65, cy + r * 0.60], fill=OFF)
    elif name == "map-marker":
        r = s * 0.26
        top = s * 0.14
        d.ellipse([cx - r, top, cx + r, top + 2 * r], fill=ON)
        d.polygon(
            [
                (cx - r * 0.78, top + r * 1.35),
                (cx + r * 0.78, top + r * 1.35),
                (cx, s * 0.92),
            ],
            fill=ON,
        )
        hr = r * 0.38
        d.ellipse([cx - hr, top + r - hr, cx + hr, top + r + hr], fill=OFF)
    elif name == "check":
        d.line([s * 0.20, s * 0.52, s * 0.42, s * 0.74], fill=ON, width=lw + 1)
        d.line([s * 0.42, s * 0.74, s * 0.80, s * 0.28], fill=ON, width=lw + 1)
    elif name == "clock":
        r = s * 0.36
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ON, width=lw)
        d.line([cx, cy, cx, cy - r * 0.55], fill=ON, width=lw)
        d.line([cx, cy, cx + r * 0.45, cy], fill=ON, width=lw)
    elif name == "alert":
        d.polygon([(cx, s * 0.14), (s * 0.92, s * 0.84), (s * 0.08, s * 0.84)], fill=ON)
        d.line([cx, s * 0.38, cx, s * 0.62], fill=OFF, width=lw)
        d.ellipse([cx - lw * 0.7, s * 0.68, cx + lw * 0.7, s * 0.68 + lw * 1.4], fill=OFF)
    elif name == "battery":
        bw, bh = s * 0.52, s * 0.76
        d.rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], outline=ON, width=lw)
        d.rectangle(
            [cx - bw * 0.18, cy - bh / 2 - lw * 1.6, cx + bw * 0.18, cy - bh / 2], fill=ON
        )
        d.rectangle(
            [cx - bw / 2 + lw, cy - bh * 0.10, cx + bw / 2 - lw, cy + bh / 2 - lw], fill=ON
        )
    else:
        d.rectangle([0, 0, s - 1, s - 1], outline=ON, width=lw)

    return mask


def draw_icon(d: ImageDraw.ImageDraw, name: str, x, y, size, fill):
    """Procedural stand-ins. The panel draws real MDI bitmaps.

    Stencilled into a `size x size` tile and blitted at (x, y), the way the
    firmware's `image->draw()` blits exactly get_width() x get_height():
    nothing lands outside [x, x+size) x [y, y+size), and the pixels the
    glyph does not set are left as they were.
    """
    d.bitmap((x, y), _icon_mask(name, size), fill=fill)


def _resolved_rect_radius(r_raw: Any, w: int, h: int, where: str, ctx: Ctx) -> int:
    """`r` for a filled rect: a non-negative integer, clamped to
    `(min(w, h) - 1) // 2` (docs/plans/dragon-feedback.md D10). Anything
    else — not an int, a bool (JSON's `true`/`false` are not the number they
    subclass), or negative — warns once and is treated as 0, which is
    `rect`'s existing square-cornered draw, so a malformed `r` degrades to
    today's behaviour rather than a bad box.

    The bound is `min(w, h) - 1`, not `min(w, h)`: a corner disc is
    `2r + 1` px across, so at `r == min(w, h) // 2` on an *even* dimension
    the disc's far edge lands one pixel past the box on that axis (e.g.
    `w == 40`: a corner circle of `r == 20` centred at `x + 20` spans
    `[x, x + 40]`, one column wider than the box's own `[x, x + 39]`) —
    caught by the sweep in tests/renderer/test_shapes.py. `max(0, ...)`
    guards a zero-size box, where `min(w, h) - 1` would otherwise go
    negative.
    """
    if isinstance(r_raw, bool) or not isinstance(r_raw, int) or r_raw < 0:
        if r_raw:
            ctx.problems.append(f"{where}: r={r_raw!r} is not a non-negative integer; using 0")
        return 0
    max_r = max(0, (min(w, h) - 1) // 2)
    if r_raw > max_r:
        ctx.problems.append(
            f"{where}: r={r_raw} is larger than (min(w,h)-1)//2={max_r}; clamped to {max_r}"
        )
        return max_r
    return r_raw


def _resolved_thickness(t_raw: Any, where: str, ctx: Ctx) -> int:
    """`t` for an outline: an integer >= 1, clamped to `THICK_MAX`. A `t`
    that isn't an int (`bool` excluded, same as every other malformed-field
    check here), or is < 1, warns and uses 1 -- the "warn and draw
    something" rule every malformed field gets. A `t` larger than
    `THICK_MAX` warns and clamps rather than silently, unlike the
    firmware's own clamp: a bad value is authoring feedback and stays on
    this side (docs/plans/dragon-feedback.md D1).
    """
    if isinstance(t_raw, bool) or not isinstance(t_raw, int) or t_raw < 1:
        ctx.problems.append(f"{where}: t={t_raw!r} is not a positive integer; using 1")
        return 1
    if t_raw > THICK_MAX:
        ctx.problems.append(
            f"{where}: t={t_raw} is larger than {THICK_MAX}; clamped to {THICK_MAX}"
        )
        return THICK_MAX
    return t_raw


def _resolved_fill(op: dict[str, Any], where: str, ctx: Ctx) -> bool:
    """`fill` for rect/circle/poly: a plain `bool`, default `True`.

    ArduinoJson's `o["fill"] | true` yields the default for anything that
    isn't a JSON bool, while Python's `op.get("fill", True)` is truthy on
    `0`/`null`/anything else that isn't literally `False`. A `fill` that is
    present but not a `bool` therefore warns and uses the default here too,
    matching the firmware's behaviour instead of Python's own truthiness —
    otherwise `"fill": 0` would outline on the panel and fill in the
    preview.
    """
    v = op.get("fill", True)
    if not isinstance(v, bool):
        ctx.problems.append(f"{where}: fill={v!r} is not true/false; using true")
        return True
    return v


def _draw_rounded_rect(
    dr: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, r: int, col
) -> None:
    """The seven shapes a rounded filled rect is built from (D10): the
    middle band, the two side bands and four corner circles, all onto the
    same `dr` so `paint()`'s single stencil pass keeps them at one absolute
    dither phase — the firmware draws the identical seven shapes through
    one `MixDisplay` for the same reason (`display_list.h`'s `rect` branch).

    A band collapses to nothing (not a negative-width `rectangle` call) once
    `r` reaches `min(w, h) // 2` — the caller's own clamp — since `r` this
    large leaves no straight run between the corners on that axis.

    Eyeball parity, not pixel parity, with the firmware: PIL's `ellipse` and
    ESPHome's own midpoint circle routine round their outlines slightly
    differently, so the handful of pixels right at each corner's own arc can
    differ by a pixel between the two renderers, the same standard the rest
    of this file's shapes are held to.
    """
    # r == 0 has no rounding to draw -- the side-band rectangles below would
    # come out as [x, y+0, x-1, y+h-1] (x1 < x0) and PIL raises on that;
    # the caller already only takes this branch for r > 0.
    assert r > 0, "_draw_rounded_rect() is for r > 0; draw a plain rect for r == 0"
    if w - 2 * r > 0:
        dr.rectangle([x + r, y, x + w - r - 1, y + h - 1], fill=col)
    if h - 2 * r > 0:
        dr.rectangle([x, y + r, x + r - 1, y + h - r - 1], fill=col)
        dr.rectangle([x + w - r, y + r, x + w - 1, y + h - r - 1], fill=col)
    for cx, cy in (
        (x + r, y + r),
        (x + w - 1 - r, y + r),
        (x + r, y + h - 1 - r),
        (x + w - 1 - r, y + h - 1 - r),
    ):
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)


def _valid_poly_points(raw: Any) -> list[tuple[int, int]] | None:
    """`pts` parsed to a list of `(x, y)` int pairs, or `None` if it isn't
    at least three of them (docs/plans/dragon-feedback.md D12).

    `raw` is always a `list` by the time this runs — its only caller
    checks `_op_required_field_problem()` first, which has already
    guaranteed that — so the length check below is the actual first
    condition for `poly`, not a shape check.

    Strict about the shape — a list of exactly-two-element lists/tuples of
    plain `int`s, `bool` excluded the way every other malformed-field check
    in this module excludes it — because the fill rule below is integer
    arithmetic and a float coordinate would silently mean something
    different on the two sides. Mirrors draw_poly()'s own all-or-nothing
    parse: one bad point invalidates the whole op, same as `rows` in
    `sprite`.
    """
    if len(raw) < 3:
        return None
    pts: list[tuple[int, int]] = []
    for p in raw:
        if (
            not isinstance(p, (list, tuple))
            or len(p) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in p)
        ):
            return None
        pts.append((p[0], p[1]))
    return pts


def _poly_spans(pts: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Even-odd scanline fill (docs/plans/dragon-feedback.md D12) — mirrors
    `poly_spans()` in display_list.h integer for integer, including the
    crossing's rounding with negative operands, so the two are bit-for-bit
    the same raster and the fill is not left to PIL to interpret.

    For each integer scanline `y` from `min(ys)` to `max(ys)` inclusive:
    take each edge of the closed point list — consecutive points, plus the
    closing edge from the last point back to the first — with `y0 != y1`.
    It contributes a crossing when `min(y0, y1) <= y < max(y0, y1)` —
    half-open, so a vertex shared by two edges is counted on exactly one of
    them, never twice and never zero times. The crossing's x is
    `x0 + (y - y0) * (x1 - x0) // (y1 - y0)`: floor division, rounding
    toward negative infinity for a negative operand on either side. Python's
    `//` already means exactly that, so — unlike the C++ mirror, which has
    to reach for a sign-correct `floor_div()` because `/` truncates toward
    zero — this line needs no helper of its own to get the same answer.

    Crossings on a scanline are sorted and paired up (1st/2nd, 3rd/4th, ...)
    into `(y, xa, xb)` spans, each filled **inclusive** of both ends. Return
    order is scanline by scanline, top to bottom, left to right within a
    scanline — the order `draw_poly()` emits them in too, though nothing
    downstream depends on that beyond making a diff readable.

    The scanline range is clamped to `[0, HEIGHT)` and each span's x to
    `[0, WIDTH)` **before** anything is appended
    (docs/plans/dragon-feedback.md D12): a polygon whose points sit far
    outside the canvas — but inside `MAX_COORD` — must not make this
    loop, or its output, scale with how far outside it they are. A span
    that clamps to nothing
    (`xa > xb` after clamping) is dropped rather than appended empty or
    inverted.
    """
    ys = [p[1] for p in pts]
    y_lo = max(0, min(ys))
    y_hi = min(HEIGHT - 1, max(ys))
    n = len(pts)
    spans: list[tuple[int, int, int]] = []
    for y in range(y_lo, y_hi + 1):
        xs: list[int] = []
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            if ay == by:
                continue  # horizontal edges never cross a scanline
            edge_lo, edge_hi = (ay, by) if ay < by else (by, ay)
            if edge_lo <= y < edge_hi:
                xs.append(ax + (y - ay) * (bx - ax) // (by - ay))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            xa, xb = max(0, xs[i]), min(WIDTH - 1, xs[i + 1])
            if xa <= xb:
                spans.append((y, xa, xb))
    return spans


def _bresenham_points(x1: int, y1: int, x2: int, y2: int):
    """The panel's own line rasterisation, walked pixel by pixel — mirrors
    `esphome::display::Display::line()` (esphome/components/display/
    display.cpp) exactly, integer for integer, rather than delegating to
    PIL's `ImageDraw.line()`.

    That distinction matters here specifically because it doesn't for the
    plain `line` op: PIL's `width=` parameter centres a thick stroke on the
    path, while the firmware's `thick_line()` (`_thick_line_points` below)
    offsets `t` parallel 1px lines to one side — the two already draw
    visibly different pixels for `t > 1`, which is accepted as eyeball
    parity for `line`/`rect` (docs/plans/dragon-feedback.md D10) because
    nothing has ever diffed them. `poly`'s outline is diffed
    (tests/parity/test_poly.py), so it earns its own exact walk instead
    of inheriting that gap.
    """
    dx = abs(x2 - x1)
    sx = 1 if x1 < x2 else -1
    dy = -abs(y2 - y1)
    sy = 1 if y1 < y2 else -1
    err = dx + dy
    x, y = x1, y1
    while True:
        yield x, y
        if x == x2 and y == y2:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _cs_outcode(x: int, y: int, xmin: int, ymin: int, xmax: int, ymax: int) -> int:
    """Cohen-Sutherland outcode: which side(s) of `[xmin,xmax] x
    [ymin,ymax]` `(x, y)` falls outside on. Mirrors `cs_outcode()` in
    display_list.h bit for bit (docs/plans/firmware-bounds.md D4's review
    amendment)."""
    code = 0
    if x < xmin:
        code |= 1  # left
    elif x > xmax:
        code |= 2  # right
    if y < ymin:
        code |= 4  # bottom
    elif y > ymax:
        code |= 8  # top
    return code


def _clip_line_cs(
    x1: int, y1: int, x2: int, y2: int, xmin: int, ymin: int, xmax: int, ymax: int
) -> tuple[int, int, int, int] | None:
    """Cohen-Sutherland line clip, mirroring `clip_line_cs()` in
    display_list.h (docs/plans/firmware-bounds.md D4's review amendment):
    `None` when the segment misses `[xmin,xmax] x [ymin,ymax]` entirely,
    else the clipped `(x1, y1, x2, y2)`. Without this, `poly`'s outline
    (up to `POLY_MAX_PTS` edges, each as long as `2 * MAX_COORD`, `t` up
    to `THICK_MAX`) would walk a Bresenham line, one Python-level
    `dr.point()` call per pixel, of a length bounded only by the
    coordinate limit rather than the canvas -- hundreds of millions of
    calls in the worst case.

    Integer division here is Python's own `//`, which is already a
    genuine floor -- the same floor `clip_line_cs()` gets in C++ by
    calling the header's own `floor_div()` rather than `/` (which
    truncates toward zero) for these same four expressions. The two
    disagreed on which pixel a clipped endpoint lands on before that fix:
    confirmed by brute force over legal edges against the production clip
    box -- the canvas expanded by `THICK_MAX`, not `MAX_COORD` -- roughly
    11.5% of off-canvas edges clipped to an endpoint one row or column
    apart, some of them drawing a visibly different pixel set on the two
    sides. `poly`'s outline is the one shape in this file held to
    pixel-exact parity rather than the eyeball parity `line`/`rect`
    outlines get (docs/SPEC.md), so this had to be exact, not merely close.
    """
    code1 = _cs_outcode(x1, y1, xmin, ymin, xmax, ymax)
    code2 = _cs_outcode(x2, y2, xmin, ymin, xmax, ymax)
    while True:
        if not (code1 | code2):
            return x1, y1, x2, y2
        if code1 & code2:
            return None
        code_out = code1 or code2
        if code_out & 8:  # top
            x = x1 + (x2 - x1) * (ymax - y1) // (y2 - y1)
            y = ymax
        elif code_out & 4:  # bottom
            x = x1 + (x2 - x1) * (ymin - y1) // (y2 - y1)
            y = ymin
        elif code_out & 2:  # right
            y = y1 + (y2 - y1) * (xmax - x1) // (x2 - x1)
            x = xmax
        else:  # left
            y = y1 + (y2 - y1) * (xmin - x1) // (x2 - x1)
            x = xmin
        if code_out == code1:
            x1, y1 = x, y
            code1 = _cs_outcode(x1, y1, xmin, ymin, xmax, ymax)
        else:
            x2, y2 = x, y
            code2 = _cs_outcode(x2, y2, xmin, ymin, xmax, ymax)


def _thick_line_points(x1: int, y1: int, x2: int, y2: int, t: int):
    """Mirrors `thick_line()` in display_list.h: `t` parallel 1px runs of
    `_bresenham_points`, offset the same way the firmware offsets
    `it.line()` calls — vertical thickens in x, horizontal in y, anything
    else (a genuine diagonal) thickens in y only. `t <= 1` is a single
    plain line, same as the firmware's early return.

    Every segment is clipped to the canvas expanded by `THICK_MAX` on
    every side before it's walked (docs/plans/firmware-bounds.md D4's
    review amendment; see `_clip_line_cs()`'s own docstring for why this
    stays within poly's existing pixel-parity contract with the firmware).
    """
    xmin, ymin = -THICK_MAX, -THICK_MAX
    xmax, ymax = WIDTH - 1 + THICK_MAX, HEIGHT - 1 + THICK_MAX

    def _clipped(lx1: int, ly1: int, lx2: int, ly2: int):
        clipped = _clip_line_cs(lx1, ly1, lx2, ly2, xmin, ymin, xmax, ymax)
        if clipped is not None:
            yield from _bresenham_points(*clipped)

    if t <= 1:
        yield from _clipped(x1, y1, x2, y2)
        return
    vertical = x1 == x2
    horizontal = y1 == y2
    for i in range(t):
        if vertical:
            yield from _clipped(x1 + i, y1, x2 + i, y2)
        elif horizontal:
            yield from _clipped(x1, y1 + i, x2, y2 + i)
        else:
            yield from _clipped(x1, y1 + i, x2, y2 + i)
