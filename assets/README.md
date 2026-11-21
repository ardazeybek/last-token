# assets

README images. Each PNG is rendered from an HTML source in `src/` (design rules: `../DESIGN.md`).

| File | What it shows |
|---|---|
| `logo.svg` | The mark: clay tile, an L of two tokens, the last token kept. |
| `install-button.svg` | Clay "Install in 30 seconds" button of the README header. |
| `banner.png` | Top banner: logo, name, tagline, three facts and a stacked-token drawing. |
| `highlights.png` | "Why Last Token?": four reasons in one row. |
| `how-it-works.png` | One session's context size with the six levers marked, plus the lever list. |
| `token-trap.png` | Indexed slopegraph: tokens −34 % while cost +69 % (the early token-cutting version). |
| `quota-formula.png` | Quota per 1M tokens by token type; 1 cache write ≈ 1 output ≈ 30 cache reads. |
| `benchmark.png` | Three setups on the 32-step task: quota, rules, recall, tests. |
| `install.png` | The three install steps and the installer's success line. |

## src/
| File | Purpose |
|---|---|
| `base.css` | Shared tokens (colors, fonts, panel) for every image. |
| `fit.js` | Measures the panel height so the screenshot is cropped exactly. |
| `render.sh` | Renders `src/<name>.html` → `<name>.png` at 2× with headless Chromium. |
| `<name>.html` | Source of `<name>.png`. |

## Regenerate
```sh
assets/src/render.sh            # all of them
assets/src/render.sh banner      # one
```
Needs a Chromium (Playwright cache or system) and network for Google Fonts. Keep each PNG under 400 KB.
- real-session.png — real `/lt-savings` output from one long session (src/real-session.html)
- social.png — GitHub social preview 1280×640 (src/social.html), upload in Settings → Social preview
- support-*.png — Clipio-style support cards: issues, discussions, mail (src/support-*.html + support.css)
- contribute.png — three ways to help, links to CONTRIBUTING.md (src/contribute.html)
- license.png — MIT, independence note, star request (src/license.html)
- updates.png — self-update flow (src/updates.html)
- faq.png — short FAQ answers (src/faq.html)
