# Fonts and icons: four families, three styles, eleven sizes; text decorations; eight activity icons

Status: decided 2026-09-19, nothing built. Input is the family design
write-up of the same date ("E-paper panel — fonts and icons to add"), plus
Alex's follow-up question: if the panel is going to carry several
typefaces, should each come in several sizes, and should the text op grow
styles such as underline? Everything below was checked against the
firmware, the installed ESPHome (2026.8.2) and the actual font files; the
numbers are measured, not guessed.

**Decisions at a glance.**

- A font is `family[-bold|-italic]/size`; size is a slot (`xs sm md lg xl`)
  or a pixel count, both accepted, the slot spelling recommended. The old
  bare `xl lg md sm xs` stay as aliases for Instrument Sans, so nothing
  already published reflows; bare `mono` is dropped. An unknown font still
  skips the op, on the wall and in the preview alike. (Decision 1)
- Petrona, Instrument Sans and Karla, each in regular, bold and italic,
  plus mono regular, every one at 22 24 26 28 32 36 40 44 48 54 84: 110
  faces, ~3.8 MB of flash on a ~7.9 MB app slot. 12 and 18 px dropped for
  now. (Decision 2)
- The face table, the cell-height data and the YAML font block are
  generated from one source; the preview needs seven variable TTFs.
  (Decision 3)
- Icons use the same five slots as fonts, at the same pixel sizes, with
  the pixel count accepted as an alias and nothing else; every icon, the
  eight new lucide ones and the eleven MDI ones, at all five. The lucide
  icons are rasterised once to committed 1-bit PNGs that the firmware
  compiles and the preview blits — the same file on both sides.
  (Decision 4)
- `deco: "underline" | "strike"` on the text op, zero flash, one rule per
  printed line. (Decision 5)
- Four work packages, landed as nine reviewed batches in four waves (Sonnet
  implements, Opus attacks, this session judges and commits), then four
  Opus reviewers with one lens each; no open questions.

## The question

The write-up asks for two things and is right about both:

1. **Four faces** — Petrona 600, Petrona italic 500, Karla 400, Karla 700 —
   filling the existing size slots, plus one new 40 px italic slot. The
   italic is the load-bearing one.
2. **Eight icons** at 36 px, named for the family activity
   (`school-day`, `daycare`, `taekwondo`, `swim`, `helper`, `appointment`,
   `family-meeting`, `closed`), each drawn from the lucide icon it names.

It also states the contract correctly: `describe()` is the source of truth,
the composing side hardcodes nothing, and a face or icon that did not
compile shows up as a `preview()` warning, not a silent fallback. That is
how the renderer already works (`fonts.py`, `ICONS`, `vocabulary()`), so
nothing on that side of the contract needs to change.

What the write-up leaves open, and Alex asked about, is the shape of the
vocabulary once there is more than one typeface: whether `xl`/`lg`/`md`
stay the names, whether a face exists at one size or several, and whether
"style" means compiled glyphs or something the text op can do at draw time.

## What was checked

**Fonts are a name-keyed map in the firmware.** `DisplayListAssets.fonts`
is `std::map<std::string, BaseFont*>`; the text op looks `f` up by string.
A new name is one YAML `font:` entry plus one `a.fonts["..."] = id(...)`
line. Nothing about the op loop cares how many faces exist or what they are
called (`display_list.h:131`, `epaper-schedule.yaml:305`).

**ESPHome's Google Fonts loader takes any weight and `italic: true`.** The
2026.8.2 font component builds
`css2?family=Petrona:ital,wght@1,500` from `{type: gfonts, family, weight,
italic}`, so Petrona 600, Petrona 500 italic and Karla 400/700 are plain
config. No local font files in the firmware tree.

**Both new families cover GF_Latin_Core completely**, including the two
characters the write-up flags: U+2014 em dash and U+2019 curly apostrophe
are in all four files (Petrona, Petrona Italic, Karla, Karla Italic; 319 of
319 code points each). Instrument Sans already compiles it today; its
italic file should be checked the same way in P2. `gf_latin_core.txt`
already lists both, so `check()`'s uncompiled-glyph warning is unchanged.

**Flash is not the constraint.** ESPHome stores each face as packed 1-bpp
glyph bitmaps in flash (not RAM — nothing here touches the heap the
2026-09-19 sprite incident blew). Estimated from the glyph bounding boxes
the same way `font/__init__.py` packs them, the panel's six faces cost about
236 KB today; the 110-face set in Decision 2 is about 3.8 MB. ESPHome's
partition table gives each OTA app slot on this 16 MB board about 7.9 MB,
so it fits with room. The per-face costs that remain are build time and a
row in `describe()`.

**The lucide SVGs go through the same path the MDI icons do.** ESPHome's
`file:` image loader rasterises any SVG with `resvg` at the `resize` size
and, because the result is black-on-transparent, `type: BINARY` takes the
alpha channel as the ink — and takes a black-on-transparent PNG the same
way, which is what lets Decision 4 compile the committed raster. Rendering the eight lucide files at 36×36 through
`resvg_py` exactly as `components/file/image.py` does gives clean 3 px
strokes with round caps (the 24-unit lucide grid scales 1.5×; `book-open`,
`star` and `waves` were inspected as bitmaps). `stroke="currentColor"`
renders black, as it must.

**The preview can select every instance it needs.** Google Fonts ships all
of these as variable fonts; Pillow's `set_variation_by_name()` finds
`SemiBold` and `ExtraBold` in Petrona, `Medium Italic` in Petrona Italic,
`Regular`/`Bold` in Karla and `Italic` in Karla Italic. That is the same
mechanism `load_font()` uses for Instrument Sans's Bold today.

## Decision 1: a face is named `family[-bold|-italic]/size`, where size is a slot or a pixel count. (Decided 2026-09-19.)

Today the font name *is* the size slot (`xl` = 84 px Instrument Sans Bold),
which works while there is one typeface. With three it conflates two axes:
the write-up's own table has to say "xl, should be Petrona 600" and invent a
name (`italic`) for a size.

So a font name is `<family>[-bold|-italic]/<size>`:

- **family** is the typeface: `petrona`, `instrument`, `karla`, `mono`
  (JetBrains Mono, regular only).
  An earlier draft used roles (`serif`, `sans`) so a typeface could be
  swapped without touching documents; with two sans faces compiled side by
  side the role name stops meaning one thing, and documents are regenerated
  from `describe()` anyway, so the typeface name is the honest one.
- **style** is `-bold`, `-italic`, or nothing for the family's regular
  weight. No bold italic.
- **size** is a slot or a pixel count, and both spellings of the same face
  are accepted:

| slot | px |
|---|---|
| `xl` | 84 |
| `lg` | 48 |
| `md` | 36 |
| `sm` | 28 |
| `xs` | 22 |

`karla/lg` and `karla/48` are the same font. A ladder size that is not a
slot — the write-up's 40 px italic — has only the pixel spelling,
`petrona-italic/40`. The docs recommend the slot spelling ("use the preset
sizes unless you have a reason not to"), so a composer thinks in `karla/sm`
and `petrona/lg` and reaches for a pixel count when the design calls for
one. A pixel count that is not on the ladder (Decision 2) is not compiled:
`karla/41` warns and skips like any unknown font, and `describe()` lists
exactly the sizes that exist. This mirrors how icons are keyed, `name/z`.

The **canonical** name — the key `describe().fonts` lists — is the slot
spelling when the size is a slot and the pixel spelling otherwise. Every
other accepted spelling is an alias, listed on the face's own entry:

```json
"petrona/lg":        {"px": 48, "slot": "lg", "aliases": ["petrona/48"], ...}
"petrona-italic/40": {"px": 40, "slot": null, "aliases": [], ...}
"instrument-bold/xl": {"px": 84, "slot": "xl", "aliases": ["instrument-bold/84", "xl"], ...}
```

Five of the six existing bare names (`xl lg md sm xs`) stay as aliases
and keep pointing at **Instrument Sans**, the face they always meant. Because
Instrument Sans stays compiled, an old document (`samples/display.json`,
the swatch sheet, every example in `compose.md`) renders pixel-for-pixel
as it does today rather than reflowing into Karla; the write-up's slot
mapping ("xl should be Petrona 600") is a statement about which face the
*design* uses for each job, which its style skill reads from `describe()`
by the new names.

| bare alias | canonical |
|---|---|
| `xl` | `instrument-bold/xl` |
| `lg` | `instrument-bold/lg` |
| `md` | `instrument/md` |
| `sm` | `instrument/sm` |
| `xs` | `instrument-bold/xs` |

Bare `mono` is dropped: `mono/24` (or `mono/sm`, `mono/lg`, …) is the
name. Nothing published uses it — `samples/display.json` and the swatch
sheet don't — and the one document that does, `samples/vocabulary.json`,
is updated in P1 along with `compose.md`'s mention. It goes because it is
the only bare name that would not be a size, and a lone exception to
"bare names are the five legacy Instrument Sans slots" is not worth
carrying. The five stay only because `text`'s default `f` is `md` and
`fmt`'s is `xs`, and old documents and tests spell them; dropping them too
is a follow-up if they turn out unused, and would move those two defaults
to `instrument/md` and `instrument-bold/xs`.

In the firmware every spelling is one more `a.fonts["..."] = id(...)` line
pointing at the same compiled font; the map is string-keyed and does not
care. In the renderer `FONTS` holds canonical names and a `FONT_ALIASES`
map resolves the rest before lookup, so `check()`, `Ctx.font()` and the
bezel check all see one name. A parity test reads the YAML's `a.fonts[...]`
keys and asserts they equal canonical names + aliases from the table —
the font analogue of the existing glyph-set parity test — so the two sides
cannot disagree about which spellings exist. An old document's `meta.hash`
does not change either way — it covers ops, not glyphs.

Not doing: a bare `italic` name (the write-up's "new slot"). Under this
scheme the italic is `petrona-italic/40`, and there is nothing for `italic`
to alias that a composer reading `describe()` would need.

**An unknown font skips the op; nothing falls back to another face.** This
is today's behaviour on both sides and it stays. The firmware logs
`unknown font 'karla/41'` and `continue`s past the op; the renderer's
`Ctx.font()` records `unknown font 'karla/41'` as a problem and draws
nothing, so `validate` and `preview` report it and the preview shows
exactly the gap the wall will show. Warnings never block a publish, so a
document with a bad font name still goes out — with the line missing, not
silently re-set. The alternative, falling back to `instrument` at the
nearest size, was considered and rejected: a substituted face has different
metrics, so the fallback would reflow or overlap its neighbours rather
than leave a clean hole, and it would hide from the composer the one thing
`preview` exists to show. `docs/SPEC.md` already states the rule ("a typo'd
font makes something vanish, while a typo'd colour leaves it present and
black") and keeps it.

What P1 does improve is the message. With a two-axis name there are more
ways to be nearly right, so `check()`'s warning says which half is wrong:
`unknown font 'karla/41': karla is compiled at 22 24 26 28 32 36 40 44 48
54 84` for a bad size, `unknown font 'karl/40': families are petrona, instrument, karla (each
also -bold and -italic) and mono` for a bad family. The
firmware's log line stays as it is; the preview is where the composer
reads it.

## Decision 2: every family and style at every size on one ladder. (Decided 2026-09-19.)

The first draft of this plan proposed thirteen faces chosen by use. Alex's
call: the panel has no rasteriser, so every size a composer might want has
to be compiled, and flash is the one resource with room to spare — so
compile the full set and let `describe()` say so in one line.

**Families and styles**, with the weight each style compiles:

| family | typeface | regular | `-bold` | `-italic` |
|---|---|---|---|---|
| `petrona` | Petrona | 600 | 800 | 500 italic |
| `instrument` | Instrument Sans | 400 | 700 | 400 italic |
| `karla` | Karla | 400 | 700 | 400 italic |
| `mono` | JetBrains Mono | 400 | — | — |

Petrona's "regular" is 600 and its italic 500 because those are the weights
the design specified; on this panel the family's default weight is whatever
reads right at 1 bpp, and `describe()` reports the number. `petrona-bold` at
800 is the one weight the design did not ask for, there so the serif has a
heavier step like the other two families (settled 2026-09-19). Instrument Sans is kept so the
old bare names keep rendering as they always did; its italic is compiled
too, since the file is there and the cost is one row.

**Sizes.** Every family-style is compiled at the same eleven sizes:

```
22  24  26  28  32  36  40  44  48  54  84
```

An earlier draft compiled 84 only for the two faces that needed it, 24
only for mono, and mono only at 24; Alex's call is that a size on the
ladder is on it for every family, so nothing has to explain why
`karla-bold/84`, `petrona/24` or `mono/lg` is missing. The one thing that was ever per-size about mono is
`ink_height`, the count of rows a full-height glyph inks (31 at 24 px),
which block art is stacked by; the metrics script in Decision 3 measures it
for every mono size the same way it measures cell heights.

12 and 18 px were on the first ladder and are dropped for now. On this
panel a pixel is 0.17 mm, so an 18 px face has a cap height of about 2 mm:
readable with your nose at the glass, not from where anyone stands to look
at a wall. 22 px (about 2.6 mm caps) is the honest floor for the panel's
purpose, and it is also where today's contrast rule already holds (below).
Either rung is one number in `SIZES` if a use turns up.

That is 10 family-styles × 11 sizes = **110 faces**. Measured cost
(packed 1-bpp glyph bitmaps, estimated the way `font/__init__.py` packs
them; 24 interpolated between 22 and 26 for the proportional faces,
Instrument Sans styles estimated from Karla's, which they match within a
few KB; mono measured at every size with its box-drawing and block
glyphs included, which is why it costs nearly double):

| KB per face | 22 | 24 | 26 | 28 | 32 | 36 | 40 | 44 | 48 | 54 | 84 | sum |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| each proportional family-style | 10 | 12 | 13 | 14 | 18 | 22 | 27 | 32 | 37 | 46 | 110–127 | ≈ 350 |
| `mono` | 19 | 22 | 26 | 29 | 35 | 44 | 54 | 64 | 75 | 92 | 218 | ≈ 680 |

Nine proportional family-styles plus mono is about **3.8 MB**, against
~236 KB today. The 84 px rung is a third of it on its own. ESPHome's partition table for
this board's 16 MB flash gives each OTA app slot about 7.9 MB, and the
firmware itself is well under 2 MB, so this fits with room. The build's own
size line is the number to record here once it exists.

Cell heights (Pillow ascent + descent, the value `describe()` reports as
`cell_height`) run 25 at 22 px to 60–62 at 54 px and 96 at `petrona/84`;
with 110 faces they and mono's `ink_height` are generated, not hand-typed
(Decision 3). Line height
stays `round(px * 1.24)` for every face, as the write-up asks.

**The contrast floor does not move.** `check()` says 3:1 is the floor
because every compiled size is WCAG large text. With the ladder starting at
22 that stays true in spirit — 22 px bold is large text outright, and the
regular and italic faces at 22 sit a hair under the strict 24 px line but
well above anything a screen rule was written for — so the rule and the
checker are unchanged. Had 18 stayed, the checker would have needed a
*stricter* floor for it (4.5:1, solid inks only), never a softer one: the
question was whether 18 could be read at all, not whether it could be
allowed to contrast less. The existing warning that a mixed ink shifts
toward its lighter ink as text stands as it is.

## Decision 3: the table is generated data on both sides; the preview follows it.

With 110 faces, two things that were hand-maintained for six become
generated:

**`fonts.py`'s table is built from families × styles × the ladder, not
typed out.** A `Family` record per typeface (file, the weight and named
instance for each of its styles) and the `SIZES` tuple produce every
`Face` at import. `Face` grows `family`, `style`, `italic`, `weight` and
`variation` (the named instance `load_font()` selects, replacing `bold`),
and `describe()` reports them per face, plus `slot` and `aliases`, derived
from `px` via Decision 1's tables. 110 entries of ten short fields is a few
KB of JSON — the composer reads it once per composition, and `compose.md`
summarises it in two lines (the families, the ladder, the slot names).

**Cell heights are a committed data file, checked by a test, not typed
into the table.** `fonts.py` today stores `cell_height` by hand so that a
font swap that changes metrics fails `test_cell_height_matches_getmetrics`
instead of silently reflowing. That property is worth keeping and the
hand-typing is not: a script (`display-mcp-cli font-metrics`, or a `python
-m` entry in `fonts.py`) measures every face from the font files and writes
`render/font_metrics.json` — `cell_height` for every face and
`ink_height` for every mono size, the latter by rendering `█` and counting
inked rows as `test_mono_ink_height_matches_a_measured_block_glyph` does
today; `Face.cell_height`/`ink_height` read from it; the test re-measures
and diffs. A font swap still fails a test; adding a size is
one number in `SIZES` and a re-run of the script.

**The YAML's `font:` block and `a.fonts[...]` lines are generated from the
same table.** 110 `font:` entries plus 110 canonical `a.fonts` lines plus
every alias is ~400 lines nobody should type twice. The same script emits
them; the existing parity test (`_yaml_font_entries()`) grows into "the
YAML's entries and keys equal what the table generates", the font analogue
of the glyph-set parity test. The YAML stays a checked-in file — ESPHome
reads it as-is — with a `# generated by ... do not edit` fence around the
block. ESPHome fetches each `gfonts` weight/italic combination once and
caches it, so the build cost is rasterising 110 faces, not 110 downloads.

**What gets downloaded, and by whom.** The two sides get their fonts
differently, and nothing is shared between them:

- The **firmware** downloads nothing you manage. Each `font:` entry is
  `{type: gfonts, family, weight, italic}` and ESPHome fetches the exact
  static instance from Google Fonts at build time, caching it under
  `.esphome/`. No font file lives in `firmware/`.
- The **preview** (`display_mcp.render`, on the Pi and on a dev machine)
  needs one variable TTF per family per slant, because Google Fonts ships
  every weight of a family in one upright file and one italic file. Seven
  files in all, fetched by `deploy/fetch-fonts.sh` from
  `github.com/google/fonts` (`ofl/<slug>/`):

| preview file (`Face.file`) | `ofl/` slug | upstream file | serves | instance `load_font()` selects |
|---|---|---|---|---|
| `Petrona.ttf` | `petrona` | `Petrona[wght].ttf` | `petrona` (600), `petrona-bold` (800) | `SemiBold`, `ExtraBold` |
| `Petrona-Italic.ttf` | `petrona` | `Petrona-Italic[wght].ttf` | `petrona-italic` (500) | `Medium Italic` |
| `Karla.ttf` | `karla` | `Karla[wght].ttf` | `karla` (400), `karla-bold` (700) | `Regular`, `Bold` |
| `Karla-Italic.ttf` | `karla` | `Karla-Italic[wght].ttf` | `karla-italic` (400) | `Italic` |
| `InstrumentSans.ttf` | `instrumentsans` | `InstrumentSans[wdth,wght].ttf` | `instrument` (400), `instrument-bold` (700) | `Regular`, `Bold` |
| `InstrumentSans-Italic.ttf` | `instrumentsans` | `InstrumentSans-Italic[wdth,wght].ttf` | `instrument-italic` (400) | `Italic` |
| `JetBrainsMono-Regular.ttf` | `jetbrainsmono` | `JetBrainsMono[wght].ttf` | `mono` (400) | `Regular` |

So: regular, bold and italic of each of the three families come from two
files each; mono from one. Every instance name in the last column was
confirmed present in the downloaded files (`get_variation_names()`), except
Instrument Sans Italic's, which should be confirmed the same way when it is
first fetched. Today's `InstrumentSans-Regular.ttf`/`-Bold.ttf` pair (the
same bytes written twice) collapses to the one `InstrumentSans.ttf`.

`fetch-fonts.sh` grows from two families to four, one `fetch_family` call
per file, and its `grep -vi italic` filter becomes per-destination: for the
three `-Italic` files it must *keep* the italic and drop the upright, the
reverse of today. `setup.sh` and `tests/test_deploy.py` list the seven
names. `GRID_FACE` (the preview grid overlay) becomes `instrument/22`.

`fonts_available()` and `_load_fonts()` stay table-driven; `mono` stays the
one `optional` face. Loading 110 faces at startup is 110 `ImageFont.truetype`
calls on seven files — well under a second, once.

## Decision 4: icons are committed 1-bit PNGs, compiled and previewed from the same file, at the five slots. (Decided 2026-09-19.)

**What an icon is on this panel.** The device has no SVG renderer and no
scaler. `mdi:check` in today's YAML is an SVG that ESPHome rasterises at
build time (with `resvg`, at the `resize` size), thresholds to one bit and
stores as a 36×36 bitmap in flash; `Image::draw()` blits it pixel for
pixel. An icon therefore exists only at the sizes it was compiled at, which
is why icons are already keyed `name/z` and `check/lg` does not exist. The
eight lucide icons are the same kind of thing.

**One size vocabulary for fonts and icons.** Today an icon's `z` is one of
three "size classes" — `sm` 36, `md` 56, `lg` 88 — that share their names
with the font slots but not their pixel sizes, which the composing guide
has to warn about ("two different fields that happen to share the name
`sm`"). That distinction goes. An icon is available at the **same five
slots as a font, at the same pixel sizes**:

| slot | px | 1-bit bytes per icon |
|---|---|---|
| `xs` | 22 | 61 |
| `sm` | 28 | 98 |
| `md` | 36 | 162 |
| `lg` | 48 | 288 |
| `xl` | 84 | 882 |

`z` takes the slot or its pixel count, exactly as `f` does — `school-day/lg`
and `school-day/48` are the same bitmap, the slot spelling is canonical and
recommended, and `describe()` lists icons in the same shape as fonts, with
`px`, `slot` and `aliases`. Nothing else is accepted: there is no icon
ladder, and `school-day/40` is "not compiled in" like any other unknown
name. Every icon — the eight new ones and the eleven MDI ones — is compiled
at all five; nineteen icons at five sizes is about 28 KB of flash, less
than one 84 px font face, so there is no reason to make a composer discover
a missing size.

Two consequences of re-using the font pixel sizes, both accepted:

- **Anything published that uses an icon changes size on the next reflash.**
  `sm` was 36 px and becomes 28; `lg` was 88 and becomes 48. The sample
  footer's `battery/sm` (`samples/display.json`, the example in
  `docs/SPEC.md` and `compose.md`) is re-set to `battery/md` so it stays
  36 px; the weather icons' one published use, at `lg` 88, becomes `xl` 84.
  Unlike fonts there is no way to alias the old meaning — `sm` cannot be
  both 28 and 36 — so this is a one-time vocabulary change in a build that
  is a vocabulary change anyway, and a composer regenerating from
  `describe()` never sees it.
- **`xs` icons are marginal.** Lucide's 2-unit stroke on a 24-unit grid is
  under 2 px at 22, so simple glyphs (`check`, `star`, `closed`) read and
  detailed ones (`stethoscope`, `users`) smear. `compose.md` says so: `xs`
  for a chip glyph beside `xs` text, `sm` and up for anything meant to be
  recognised. At the other end, 84 gives lucide a 7 px stroke, which is the
  weather-hero size the write-up's day view wants.

**Source and build artefact are separate files, both committed.** Each of
the eight lucide SVGs is copied at a pinned lucide version into
`firmware/icons/src/<activity>.svg` (renamed from the picture to the
activity — `book-open.svg` → `school-day.svg` — with lucide's ISC licence
text alongside). A script, `firmware/icons/rasterize.py`, run under
ESPHome's own Python (it has `resvg_py`; the project venv does not),
renders each SVG at each of the five sizes exactly as ESPHome's
`components/file/image.py` would and writes black-on-transparent 1-bit
PNGs to `src/display_mcp/render/icons/<activity>-<px>.png` — forty files.

**Both sides consume the PNG.** The firmware compiles it — ESPHome takes
an alpha-only PNG through the same `type: BINARY` path an SVG ends up on —
and the preview's `draw_icon()` blits it. So the wall and the preview show
the identical bitmap by construction, not by remembering to rerun a
script; the SVG is only ever the input to `rasterize.py`. This is the first
time any icon has had real preview parity: the eleven MDI icons are
procedural stand-ins in `shapes.py`, "good for judging layout and weight,
not artwork".

```yaml
- { file: ../src/display_mcp/render/icons/school-day-36.png, id: ic_school_day_md, type: BINARY, transparency: chroma_key }
- { file: ../src/display_mcp/render/icons/school-day-84.png, id: ic_school_day_xl, type: BINARY, transparency: chroma_key }
```

(The exact relative path is the implementer's call; the point is one file,
referenced from both places.)

The **eleven MDI icons** keep coming from `mdi:` at build time, five
`image:` lines apiece at `resize: 22x22` … `84x84`. Their preview stand-ins
are already size-parametric, so nothing changes there; converting them to
committed rasters too is the optional tidy-up it was before. `ICON_SIZES`
becomes the font slot table, `ICONS` says all five slots for every icon,
and `describe().icon_sizes` goes away in favour of the per-icon `px`/
`slot`/`aliases` shape fonts use.

`ICONS` gains the eight names. `describe().icons` picks them up with no
other change. The write-up's fallback — anything outside the list is a
text-only row — is the composer's rule, not the renderer's, and stays
where it is.

`swim` is lucide's `waves-ladder`, not the write-up's `waves`. (Decided
2026-09-19, from the two rasterised side by side.) A pool ladder over water
reads as "swim lesson" where three wavy lines could be rain, a bath or the
beach; it is clean from `md` up and still recognisable at `sm`, where the
rungs begin to fill in. The activity name is what documents use, so the
choice is a one-file swap if it ever changes.

## Decision 5: styles come in two kinds, and only one of them is a firmware feature.

Alex's question was whether "styles like underlining" belong alongside the
new faces. The split that matters:

**Glyph styles** — italic, bold, weight, small caps, condensed — are
different outlines. On this panel they can only be compiled faces; the
firmware draws pre-rasterised bitmaps and has no way to shear or embolden
one at draw time that would look acceptable at 1 bpp. Italic and bold are
therefore already handled by Decisions 1–2: `petrona-italic/*` and
`karla-bold/*` *are* the style system, and a composer picks a style by
picking a face. This is also why the write-up is right that the italic is
load-bearing: nothing short of compiling it produces one.

**Decorations** — underline, strikethrough — are geometry drawn next to
the glyphs. They cost no flash and are cheap in the firmware: the text op
already measures every line it prints (`fit_line`/`wrap` call
`font->measure()`, and `Display::get_text_bounds()` gives the inked extent
for an aligned line), so a rule under or through it is one
`clipped_filled_rectangle()` per line after each `mix.print()`. Sketch:

```
deco: "underline" | "strike"      (text op only; fmt does not wrap and does not need it)
t   = max(2, round(px / 14))      never 1 px: a 1 px rule cannot hold a mixed ink (the write-up's 2 px floor)
underline top = y + baseline + max(2, round(px * 0.06))
strike top    = y + baseline - round(px * 0.30) - t // 2
x1, width     = get_text_bounds(x, ly, line, font, align)   per wrapped line
```

`baseline` is the `measure()` out-parameter the firmware already reads; the
Python mirror uses `font.getmetrics()[0]` and `textlength()`, with eyeball
parity like `rect`, not a differential test.

Whether to build it: **both, as one field.** (Decided 2026-09-19.) The
design write-up uses neither, and the guide should say when each earns its
place: strike for a completed
to-do that stays on the list; underline for a word or phrase that has to
stand out inside a line where a face change would be too loud — a time, a
name — and never for a heading, where a `line` op of known width is the
rule to reach for. Both values are the same firmware branch and the same
renderer branch; the only per-value code is the `y` of the rule.

Two things the guide has to say about underline specifically: the rule
sits below the descenders, so on a wrapped op the `lh` default of
`round(px * 1.24)` leaves it 1–3 px clear of the next line's ascenders and
a tighter `lh` will collide; and on a mixed-ink text the rule is drawn in
the same mix and reads lighter than the glyphs, like every thin feature.

Not doing, ever: synthetic bold or oblique, letter-spacing, per-op font
size. Each is either impossible at 1 bpp or a rebuild in disguise.

## Work packages, in the write-up's order

Fonts before icons, the italic first — but because Decision 1 changes the
naming, the first package lands the scheme and the italic together, so
there is one rename, not two.

**P1 — naming scheme, generators, Petrona.** `Family`/`SIZES` tables,
the generated `Face` set, `FONT_ALIASES` and a resolver replacing direct
`FONTS[name]` lookups in `Ctx.font()`, `check()` and the bezel check, with
the which-half-is-wrong warning; bare `mono` removed from
`samples/vocabulary.json` and `compose.md`; the metrics script and
`font_metrics.json`; the YAML generator and the grown
parity test; `vocabulary()`'s new per-face fields. Instrument Sans's
and mono's existing entries are re-expressed through the generator in the
same step (`instrument`, `instrument-bold` and `mono` at every size, the
bare aliases re-pointed to their canonical names) so there is one scheme,
not two. `compose.md` loses "`mono` is one size — no bold, no second mono
size" and its block-art paragraph says to stack by the `ink_height` of
whichever mono size is in use.
YAML: the 33 Petrona entries (three styles × 11). `fetch-fonts.sh`/
`setup.sh`/`test_deploy.py` learn the Petrona files. Tests:
`test_fonts_keys`, the "six font entries" parity assertion, `test_mcp.py`'s
describe-shape test. This is the write-up's items 1 and 2 in one reflash.

**P2 — Karla, the italics.** `karla`, `karla-bold`, `karla-italic`,
`instrument-italic` × 11; the three remaining font files in the fetch script.
Nothing old reflows: the bare aliases still resolve to Instrument Sans, so
the `fit_line`/wrap tests in `tests/renderer/test_text.py` keep their
measured truncation points, and `compose.md`'s icon-beside-text offsets
(`lg → y+6`, …) stay correct for the faces they name — the guide gains a
line saying they were measured against `instrument` and that other
families sit a few px off. Its type-scale section becomes the family
table, the ladder and the slot names.

**P3 — the icons.** `firmware/icons/src/` (SVGs, LICENSE) and
`rasterize.py`; the 40 PNGs under `render/icons/`; 95 `image:` entries and
`a.icons[...]` lines (nineteen icons × five slots, generated by the same
script that generates the font block) plus the pixel-count aliases;
`draw_icon()`'s PNG path; `ICON_SIZES` re-pointed at the font slot table,
`ICONS` saying all five slots for every icon, `z` resolved through the same
alias path as `f`; `battery/sm` → `battery/md` in `samples/display.json`,
`docs/SPEC.md` and `compose.md`, and the guide's icon-beside-text offsets
re-measured now that an icon and a font at the same slot are the same
height. Tests: every `render/icons/*.png` has an `ICONS` entry and vice
versa; every `ICONS` name/slot is in the YAML (the icon analogue of the
font-entry parity test, which does not exist today); each PNG is
alpha-only and exactly its slot's size, so ESPHome's `is_alpha_only` path
is guaranteed to take it.

**P4 — `deco: "underline" | "strike"`.** Firmware branch in the text op
(one `clipped_filled_rectangle()` per printed line, after `mix.print()`),
the renderer's mirror, `OP_FIELDS["text"]["optional"]["deco"]` defaulting
to `null` with any other value a warning that draws the text undecorated,
a SPEC paragraph under `text`, the `compose.md` guidance from Decision 5.
Tests: a rendered strike lands between the baseline and the x-height, an
underline below the descender and above the next wrapped line at the
default `lh`, and both span exactly the measured line under each `a`.
Independent of P1–P3; can run in parallel with P3.

**Prose in every package:** `docs/SPEC.md` ("six font sizes, eleven icons"
in the header and Vocabulary section), `README.md:161`, `docs/PLAN.md:179`,
the YAML header comment, `compose.md`. `docs/SPEC.md`'s Vocabulary section
becomes the canonical-name table plus the alias list.

Each package is one worktree branch, squashed to one commit on `main`
(the workflow already in use). The mono face landed the same way in
`1a19a05` and touched seventeen files; that commit is the checklist for P1
and P2.

## Implementation plan

The work is orchestrated from this session, on this branch
(`claude/epaper-fonts-icons-9d5ee9`, in this worktree), in **batches**. The
packages above say *what*; the batches below are the *order* it lands in,
each one small enough that a single agent can hold it and a single diff can
be reviewed adversarially. Batches that depend on nothing still open run at
the same time in their own worktrees and merge back here as they land.

**The loop for every batch:**

1. **Implement — a Sonnet sub-agent.** It gets the batch's brief below,
   the relevant decisions from this document verbatim, and the repo's own
   rules (`CLAUDE.md`, `docs/PLAN.md`'s tool shapes, the "settled" list).
   It writes code and tests, runs `pytest`, and for a firmware batch runs
   `esphome compile` from `firmware/`; it reports what it changed, what it
   could not do, and the test/compile output verbatim. It does not commit.
2. **Review — an Opus adversarial reviewer.** It gets the batch's diff,
   the same brief and decisions, and one instruction: try to break it. It
   is asked for concrete failure scenarios (input → wrong output or crash),
   parity gaps between `display_list.h`/the YAML and the renderer, tests
   that pass without testing the claim, and anything the brief asked for
   that the diff quietly narrowed. It reports findings ranked by severity,
   each with the scenario, not a style list.
3. **Judge — this session.** Every finding gets a verdict, recorded in the
   implementation log below: *fix* (with who fixes it), *reject* (with
   why), or *defer* (to which batch or to the final review). A one-line
   fix is done here; anything larger goes back to the same Sonnet agent
   with the finding quoted, and the fixed diff goes back to the reviewer.
   The batch is done when the reviewer has no unaddressed *fix* findings
   and the tests and compile are green.
4. **Commit.** One commit per batch on this branch, message naming the
   batch and the decisions it implements. Squashing to `main` at the end is
   Alex's call, as it was for the mount and the mono face.

**The batches, in waves.** The serial spine is the font table → the YAML
generator → the new families, because each regenerates from the last.
Everything else hangs off that spine at one point or not at all, so the
work runs in four waves; batches in the same wave run at the same time,
each in its own worktree branched from this branch, and merge back as each
lands (their code is disjoint; the only overlaps are prose in `compose.md`
and `docs/SPEC.md`, which B6 reconciles anyway).

| wave | batch | package | what lands | gate |
|---|---|---|---|---|
| 1 | B1 | P1 (renderer half) | `Family`/`SIZES` tables and the generated `Face` set for **Instrument Sans and mono only**; `FONT_ALIASES` and the resolver in `Ctx.font()`, `check()`, the bezel check; the metrics script and `font_metrics.json` (cell heights, mono `ink_height` per size); `vocabulary()`'s new per-face shape; the which-half-is-wrong warning; bare `mono` dropped from `samples/vocabulary.json` and `compose.md`. No new typeface yet, so every existing render is pixel-identical and the existing tests prove it. | `pytest` green; `samples/display.json` renders byte-identical to before. |
| 1 | B5 | P4 | `deco: "underline" \| "strike"` in `display_list.h` and the renderer; `OP_FIELDS`; the SPEC paragraph; the guide's when-to-use text and the two underline cautions; the position/width tests. The only firmware-logic change in the plan, so it goes first and gets the longest soak before the final safety review. | `pytest` green (the host-compiled parity harness covers the C++); `esphome compile` green after merge. |
| 1 | B3a | P1/P2 (deploy half) | `fetch-fonts.sh`, `setup.sh`, `tests/test_deploy.py` for the seven files, with the per-file italic filter and the Instrument Sans pair collapsed to one file. Deploy scripts only; no renderer change. | `pytest` green; the script run for real into a scratch dir produces seven files that `is_font` accepts. |
| 1 | B4a | P3 (asset half) | `firmware/icons/src/` (the eight lucide SVGs at a pinned version, renamed, with LICENSE) and `rasterize.py` run under ESPHome's Python; the 40 PNGs under `render/icons/`. Pure asset generation; nothing reads them yet. | Every PNG is alpha-only and exactly its slot's size; `rasterize.py` is idempotent (a second run changes no bytes). |
| 2 | B2 | P1 (firmware half) | The YAML generator; `epaper-schedule.yaml`'s `font:` block and `a.fonts[...]` lines regenerated for Instrument Sans × 11 × 3 styles and mono × 11, with every alias; the grown parity test; the header comment. | `pytest` green; `esphome compile` green, flash line recorded in the log. |
| 3 | B3b | P1 + P2 (the new families) | Petrona and Karla in the family table; `font_metrics.json` regenerated; YAML regenerated (all 110 faces); `GRID_FACE` → `instrument/22`; `compose.md`'s type-scale section. | `pytest` green with the fonts fetched into `./fonts`; `esphome compile` green, flash line recorded. |
| 3 | B4b | P3 (wiring half) | `ICON_SIZES` → the slot table, `ICONS` all-five for every icon, `z` through the alias path; `draw_icon()`'s PNG path; the 95 `image:` entries and `a.icons` lines, generated by the same script as the font block; `battery/sm` → `battery/md` in the sample, SPEC and guide; the icon parity and PNG-shape tests; the guide's icon offsets re-measured. Runs after B3b, not beside it: both extend the generator and regenerate the YAML. | `pytest` green; `esphome compile` green; a preview of `samples/vocabulary.json` extended with every new icon at `md` and `xl`, eyeballed. |
| 4 | B6 | prose | `docs/SPEC.md` (header counts, Vocabulary section as the family/slot tables), `README.md`, `docs/PLAN.md`, `docs/RUNBOOK.md`, the YAML header, `compose.md` end to end; `describe()`'s docstring. Nothing behavioural. | Every count and name in the prose matches `describe()`'s output, checked by the reviewer against a live call. |

Wave 1 is most of the new code, so running its four pieces at once cuts
the wall-clock roughly in half. It does not change the spend: each piece
still gets its own implementer and its own review, and the reviews are the
expensive part.

**Reflashing the panel is not a batch.** The compile is the gate the agents
can reach; putting the build on the wall, and the write-up's own check
(`preview()` a document that uses every new face and icon, `set_display`
it, look at the glass), is Alex's step after B6 or whenever a batch is
worth seeing.

**Final review — four Opus reviewers, in parallel, after B6.** Each gets
the whole branch diff against `main`, this document, and read access to
the repo; each has one lens and is told the others exist so it does not
drift into their territory:

1. **Code quality and simplicity.** Is anything in the diff more machinery
   than the decision it implements needs; duplicated logic between the
   generator, the table and the tests; names that don't match the
   vocabulary; dead code the change orphaned; a simpler shape for the
   alias resolution or the generated data.
2. **Firmware safety, ESPHome-specific.** The `display_list.h` changes
   (`deco`) against the device-safety bounds in `docs/plans/firmware-bounds.md`:
   any allocation on the heap per op or per line, any path where a legal
   document makes `get_text_bounds`/`filled_rectangle` run unbounded, the
   draw budget; the YAML changes: 110 fonts' and 95 images' worth of
   `PROGMEM`, partition headroom from the build's own numbers, boot time,
   anything the 2026-09-19 sprite incident (`docs/plans/wake-sleep-flow.md`)
   would have caught earlier.
3. **The composer's view.** It connects as an MCP client would, with no
   prior context — reads `describe()`, `guide()`, the `compose_display`
   prompt, every tool description and the `spec`/`sample` resources — and
   tries to compose a page. It reports every place the language is
   confusing, two sources disagree, a name is used before it is defined,
   a recommendation contradicts a table, or a warning message would not
   tell it what to change.
4. **Staleness.** Every doc and every code comment in the repo, against the
   branch: counts ("six font sizes, eleven icons"), names (`xl` as a font,
   `sm` as an icon class, `bold` in `describe()`), file lists
   (`InstrumentSans-Regular.ttf`), decisions this document supersedes
   (`docs/plans/dragon-feedback.md` D11's "one mono size"), and anything in
   `docs/PLAN.md`/`docs/SPEC.md` that now describes the old world.

Their findings go through the same judge step, and the accepted ones form
**B7**, implemented and reviewed the same way as any batch. The plan is
done when B7 is committed and this document's implementation log says so.

## Implementation log

*(Appended as batches land: for each, the commit, the reviewer's findings
with verdicts, and the compile's flash line where there is one.)*

## Verification

- `esphome compile` from `firmware/` after P1: the build log's flash line,
  recorded in this doc against the 3.8 MB estimate. A Google Fonts fetch
  failure or an unsupported weight fails here, not on the wall.
- `pytest`: the cell-height and parity tests are the guard that YAML and
  `fonts.py` say the same thing; they must be red between editing one and
  the other.
- The write-up's own check: `preview()` a document that uses every new
  face and icon, then `set_display` it and photograph the glass. A face the
  panel skipped is a `WARN unknown font` line in the ESPHome log and a
  missing element on the wall while the preview shows it; that gap is what
  the parity tests exist to make impossible, so a real one is a bug in
  them.
- `describe()` after each package lists exactly the compiled set, each
  face with every spelling it accepts, and the family style skill composes
  from it with nothing hardcoded — the contract the write-up commits to on
  its side.

## Open questions

None. `petrona-bold` at 800 and `swim` as `waves-ladder` were the last two,
both settled 2026-09-19. See "Decisions at a glance" at the top.
Earlier drafts of this plan — a thirteen-face matrix chosen by use, role
names (`serif`, `sans`) instead of typeface names, a ladder that started at
12 px, Instrument Sans without an italic, 24 and 84 px for some faces but
not all, mono at one size — were superseded by the decisions
above on the same day and are not preserved here.
