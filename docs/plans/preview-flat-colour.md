# Flat colour in `preview`, and the end of `--ideal`

Decided 2026-09-11.

## What happened

An agent composing a new design reported a renderer bug and called it
conclusive: `{c: blue, c2: green, mix: 50}` and `{c: green, c2: blue,
mix: 50}` rendered "completely different colors — dark green vs
blue-violet", `teal` came out "pixel-identical to forest", and every
built-in whose base ink was not black looked wrong — `cream` in particular
came out "neutral grey". It derived a rule from this ("only mixes with
`c: black` work"), redesigned its palette around the rule, and dropped a
colour it wanted.

None of it was a renderer bug. At full resolution:

- All 21 built-ins match their `docs/SPEC.md` hex exactly.
- Order symmetry holds everywhere: across all 15 ink pairs × {25, 50, 75},
  `{a,b,m}` and `{b,a,100−m}` produce identical pixel populations, and
  `{a,b,50}` equals `{b,a,50}`. Zero violations.
- `teal` is 50% green + 50% blue; `forest` is 50% green + 50% black. Not
  identical, not close.
- `{yellow, white, 50}` is 50/50 and averages to `#d6c582`, which is
  `cream` to the digit.

What the agent was looking at was an **exact 2× nearest-neighbour
downscale** of the preview PNG. `mix_on` at 50% selects the Bayer cells at
`(x+y) even`; a 2× nearest sample lands on the same cell every time, so
every 50% mix collapses to a solid patch of its `c2` ink. That single rule
reproduces the entire report, including its wording — "as if the base ink
were dropped" is literally "you only see `c2`". `teal` and `forest` both
collapse to solid green, hence "pixel-identical". `cream` collapses to the
white ink `(222, 222, 216)`, hence "neutral grey". Order-swapping flips the
phase, so the two mixes alias to opposite inks.

The agent's own rule was wrong in a way worth noting: `grey-dark/mid/light`
have `c: black` and do not survive either (25% → solid black, 50%/75% →
solid white). The pattern it saw was not about black.

## The decision

`preview` renders every mix as the single colour it averages to
(`Ink.avg`). `render()` gains `dithered_colors`, defaulting to **True** —
the panel's behaviour, and what the firmware is diffed against — and only
the MCP `preview` tool passes False.

Nothing else changes. `check()` and the CLI keep rendering dithered.

### Why a caveat in the docstring was not enough

The warning was already there, in `preview`'s docstring: *"most image
viewers scale this PNG down to fit, which aliases each mix to a solid patch
of just one of its two inks… judge colour from the named palette table."*
A careful reader hit the artifact anyway.

A docstring is read once at tool-discovery time, thousands of tokens from
the image it describes, and "judge colour from the named palette table"
asks the reader to go find that table and cross-reference a recipe. That is
three steps of effort against zero steps to believe your eyes. The eyes
win. So the caveat moved into the response, adjacent to the image, phrased
for whichever image was actually returned.

### Why warnings now ride with the image

`preview` used to discard `check()`'s output. Now it returns it, because
under flat rendering the warnings are the only thing describing what the
dither really does — specifically that a mixed *glyph* reads shifted toward
its lighter ink, which is exactly the case where the flat image is most
optimistic.

They come from `check()` rather than being recomputed off the flat canvas,
and `render()` now refuses `warn_ink=True` with `dithered_colors=False`
outright, so that is not a style preference but the only legal source.

Two warnings read pixels back off the image: `_check_contrast` (via
`_grounds`) and `_check_drew_nothing`. On a flat canvas they are measuring
an image the panel never draws. `_check_contrast` also feeds a fused blend
to `Ctx.name_of`, which can only name the six inks, so its message came out
as `white on ink is 3.0:1` — 20 of the 42 named ground/text pairs did that
before the guard.

An earlier draft of this document argued the case with numbers instead:
white text on `grey-mid` measuring 2.97:1 flat against 12.06:1 dithered.
That example died twice over. The 12.06 depended on `_dominant_ground`'s
coordinate-parity tie-break and flipped to 1.00:1 at half the positions;
and since `fd69ddc` the ground is judged by the colour it fuses to, which
is the same colour in both modes — a sweep of all 21 built-ins as grounds
against white and black text now finds **zero** disagreements. The
contrast argument for sourcing from `check()` is gone; what remains is
that the combination is illegal, that `_check_drew_nothing` still diffs
raw pixels, that `check()` adds the bezel and stale-hash checks no
`render()` produces, and that one source means `preview` and `validate`
cannot disagree.

### Why dithered rendering stays

It was considered and rejected as a simplification. Three things depend on
the canvas holding two real inks:

- `Ctx.name_of` documents the invariant that every painted pixel is one of
  the six table entries verbatim. Flat-only would make every mixed ground
  report as `"ink"`. Keeping the dithered path, and forbidding `warn_ink`
  without it, is what keeps that invariant true rather than aspirational.
- `_check_drew_nothing` exists precisely because contrast maths cannot see
  text vanishing into a same-mix ground, and its answer is to *observe real
  pixels*.
- `firmware/display_list.h` carries a bit-identity proof for `mix_on` that
  the Python mirrors; 22 of the render tests assert on dithered pixel
  shares. Without dithering there is nothing left to diff against the
  firmware, and the renderer's stated contract is firmware fidelity.

Deleting the dithered path would have removed roughly twenty lines and cost
all of that. The flat path is the cheap one.

### Why `dithered_colors` is still exposed on the tool

The code has to exist regardless, so the marginal cost of a parameter is
two lines, and an agent asked to inspect dither artifacts on a specific
feature should be able to. It re-opens the aliasing trap by design, so its
note says so explicitly rather than reusing the flat one.

## `--ideal` removed

This reverses `docs/PLAN.md`'s original "the pure-RGB `--ideal` mode stays a
CLI flag".

`IDEAL` was the pure framebuffer RGB the driver writes (`red` = `#FF0000`)
as opposed to `INK`, the Spectra 6 approximation (`red` = `#9C2E2A`). It was
reachable only from `display-mcp-cli render --ideal`; `preview` never passed
it, so no MCP caller could ever see it. The six-ink invariant it nominally
guarded is already covered in `INK` mode by
`test_render_emits_only_the_six_inks`.

One colour table, and it is the one that looks like the wall — the panel is
the thing being previewed. `tests/test_cli.py::test_render_has_no_ideal_flag`
pins the removal so the flag is not revived without revisiting this.

## Pinned by tests

1. Each of the 21 built-ins renders flat to exactly its `SPEC.md` hex, with
   the table parsed from the doc rather than copied, so the two cannot
   drift. A guard test asserts the table still covers every built-in.
2. `{blue,green,50}` and `{green,blue,50}` are byte-identical flat, and
   genuinely one pixel out of phase dithered.
3. A flat fill is uniform; a flat mixed background is uniform (the bg takes
   its own code path).
4. A document with no mixes is byte-identical in both modes. (The sample is
   *not* that document — its footer stamp is `grey-mid` — so the test swaps
   that one colour out and asserts it did.)
5. Flat and dithered differ in colour only, never in geometry: the same
   pixels are drawn, across every op type that reaches `paint_op`.
6. Dithering is still the default, including through the CLI.
7. `render()` rejects `warn_ink` on a flat canvas.
8. `Ink.avg` agrees with the ground fusing in `_grounds` for all 21
   built-ins — see below.
9. `preview` returns image + text with the right note for the mode, and its
   warnings come from `check()`. Pinned against the *real* renderer in
   `tests/test_mcp_preview_render.py`: `tests/test_mcp.py` stubs the
   renderer out, and under those fakes both dropping `dithered_colors` and
   swapping `check()` for the render's own problems passed the whole
   suite.

## Two ways to fuse a dither, kept apart on purpose

`Ink.avg` blends from the colour spec — two inks and a density — and is what
a flat preview *paints*. The fusing inside `_grounds` (added by `fd69ddc`)
averages the real pixels of a 2×2 mask tile and is what `check()` *measures*
contrast against. They compute the same physics and agree for all 21
built-ins.

Neither can be expressed in terms of the other. `_grounds` is handed
arbitrary canvas pixels — possibly spanning several ops, a knockout, or two
different mixes — and has no `Ink` to consult; `Ink.avg` runs before
anything is painted and has no pixels. So this is two formulas that happen
to agree, not one definition with two call sites, and nothing else would
notice if they drifted.

The agreement is load-bearing, because the two meet inside `preview`: the
image is painted at `Ink.avg` and the warnings shipped beside it are judged
against the fused ground. Drift means showing a colour we are not judging
you against, which is the failure this whole change exists to remove. It is
pinned by `test_ink_avg_agrees_with_the_ground_fusing_in_grounds`. If a
single definition is ever wanted, the shape is a `_fuse(colour -> count)`
helper both call — the likeliest trigger being a move to gamma-correct
blending, which would otherwise land in one of the two.

## Fixed since

The tie-break this document originally flagged as a known adjacent issue —
`_dominant_ground` choosing the ground ink with `Counter.most_common(1)`,
an arbitrary coin-flip on a 50/50 mix — was fixed in `fd69ddc`, which
replaced it with per-tile fusing. See `docs/plans/ink-mixing.md`.
