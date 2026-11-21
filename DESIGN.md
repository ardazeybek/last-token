# DESIGN — Last Token README images

Direction: data-journalism charts (uv / OWID style) on an opaque warm paper panel, so one image works on GitHub light and dark.

## Canvas
- 1280 px wide design, exported 2× PNG, transparent outside the panel, each file < 400 KB.
- Panel: `#FAF7F2`, radius 18 px, 1 px border `#E6DFD3`, padding 64 px.
- GitHub shows images at ~830 px: smallest text is 16 px at design size.

## Color (tokens in `assets/src/base.css`)
| Token | Hex | Meaning |
|---|---|---|
| `--brand` | `#2356C8` | Last Token (always this, nothing else) |
| `--cost` | `#C2452D` | Something that costs more quota |
| `--base` | `#A8A196` | Plain Claude Code, neutral baseline |
| `--ink` / `--ink-2` / `--ink-3` | `#1C1B18` / `#57534B` / `#736D64` | Text, secondary, axis/muted |
| `--rule` / `--grid` | `#E3DCCF` / `#ECE6DB` | Dividers, gridlines |
| `--term` | `#17181B` | Terminal surface only |
Palette checked with the dataviz validator. Text never takes a series color.

## Type
- Titles: Source Serif 4 600, 46 px. Body: IBM Plex Sans 400/500/600, 18–20 px. Code: IBM Plex Mono 16 px.
- Headline = the finding as a plain sentence, no trailing period (chart-title style), lede below in `--ink-2`.

## Charts
- Direct labels instead of legends; numbers in `--ink`, bold for the key value.
- Bars 22–26 px, 4 px rounded data end, anchored at the baseline. Lines 2–3 px.
- One axis only; different units are indexed to a common base (token-trap).
- Measured ranges drawn as a hatched extension (quota-formula output 3–7).

## Avoid
Dark card grids with an orange accent, mono eyebrow + giant headline, % inside a ring, purple gradients, emoji.
