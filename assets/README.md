# assets

README images. Each PNG is rendered from an HTML source in `src/` (design rules: `../DESIGN.md`).

| File | What it shows |
|---|---|
| `hero.png` | Wordmark, the promise and the headline result (−28 % plan quota, 4.99 % → 3.60 %). |
| `how-it-works.png` | One session's context size with the six levers marked, plus the lever list. |
| `token-trap.png` | Indexed slopegraph: tokens −34 % while cost +69 % (the early token-cutting version). |
| `quota-formula.png` | Quota per 1M tokens by token type; 1 cache write ≈ 1 output ≈ 30 cache reads. |
| `benchmark.png` | Three setups on the 32-step task: quota, rules, recall, tests. |
| `install.png` | The three install steps and the installer's success line. |
| `*.svg` | Previous images, kept until the README points at the PNGs. |

## src/
| File | Purpose |
|---|---|
| `base.css` | Shared tokens (colors, fonts, panel) for every image. |
| `fit.js` | Measures the panel height so the screenshot is cropped exactly. |
| `render.sh` | Renders `src/<name>.html` → `<name>.png` at 2× with headless Chromium. |
| `<name>.html` | Source of `<name>.png`. |

## Regenerate
```sh
assets/src/render.sh            # all six
assets/src/render.sh hero       # one
```
Needs a Chromium (Playwright cache or system) and network for Google Fonts. Keep each PNG under 400 KB.
- `banner.jpg` — top banner of the README (logo + tagline).
