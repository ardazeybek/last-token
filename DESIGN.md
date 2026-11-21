# DESIGN — Last Token README images

Direction: the warm, calm look of Claude's own world (ivory paper, clay accent, serif headlines, ink line drawings) with data-journalism charts on top. One opaque panel per image, so it reads on GitHub light and dark. Our own mark only: no Anthropic logo, and the README says the project is independent.

## Canvas
- 1280 px wide design, exported 2× PNG, transparent outside the panel, each file < 400 KB.
- Panel: `#FAF9F5`, radius 20 px, 1 px border `#E8E6DC`, padding 56–72 px.
- GitHub shows images at ~830 px: smallest text is 16 px at design size.

## Color (tokens in `assets/src/base.css`)
| Token | Hex | Meaning |
|---|---|---|
| `--brand` | `#D97757` | Last Token, the clay accent (darker clay `#C4633F` for icon strokes and shadows) |
| `--brand-soft` | `#F5E1D7` | Icon tiles, soft highlight bands |
| `--cost` | `#3D3D3A` | Something that costs more quota (dark slate) |
| `--base` | `#B9B6AB` | Plain Claude Code, neutral baseline |
| `--ink` / `--ink-2` / `--ink-3` | `#141413` / `#4D4C48` / `#73726C` | Text, secondary, axis/muted |
| `--rule` / `--grid` | `#E8E6DC` / `#EFEDE6` | Dividers, gridlines |
| `--term` | `#141413` | Terminal surface only |
Badges reuse the same hexes (clay, ink, slate, olive `#788C5D` for "no telemetry").

## Type
- Headlines and the wordmark: Source Serif 4, 400–600, tight tracking. Body: Hanken Grotesk 400–700, 18–22 px. Code: JetBrains Mono 16 px.
- Headline = the finding as a plain sentence, no trailing period; lede below in `--ink-2`.
- One italic clay word is allowed in the banner tagline, nowhere else.

## Logo
`assets/logo.svg`: clay rounded tile, an ivory L made of a long and a short token, one ink dot (the last token kept).

## Illustration
Ink outline (3 px, `#141413`) over ivory fills, one clay object, a soft `#F0EEE6` disc behind. No gradients, no glow.

## Charts
- Direct labels instead of legends; numbers in `--ink`, bold for the key value.
- Bars 22–26 px, 4 px rounded data end, anchored at the baseline. Lines 2–3 px.
- One axis only; different units are indexed to a common base (token-trap).
- Measured ranges drawn as a hatched extension (quota-formula output 3–7).

## Avoid
Dark neon banners, glow, purple gradients, % inside a ring, emoji inside images, the Anthropic/Claude logo.
