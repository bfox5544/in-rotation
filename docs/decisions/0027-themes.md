# 0027: Site themes

Status: accepted (2026-11-09, owner request: "Allow users to choose between A, B, and C. This option should be available in the Account tab.")

## The choice
From a comparison page of six themes, the owner picked three for visitors to choose between:

| Theme | Look | Action color | Save and focus color |
|---|---|---|---|
| **Charcoal** (default) | Dark gray, the original look | Amber `#f2b84b` | Teal `#4cd0c4` |
| **Gallery** | Light: near-white, so covers sit like prints on a wall | Cobalt `#2346d6` | Green `#0d8577` |
| **Midnight** | Deep blue-black | Coral `#ff8a66` | Periwinkle `#a6b2ff` |

Fonts, layout and the squared buttons are the same in all three.

## Where and how
- **Where:** a **Theme** section on the Account page. Visitors who aren't signed in find it under the sign-in form, and signed-in visitors find it in Profile Settings, above Account. Each option shows a five-color strip, its name and one line about it. Choosing one applies it at once.
- **Saved per browser,** in `localStorage` (`inrotation.theme`), like the For You depth (ADR 0012). It isn't part of the account, so it works for anonymous visitors and needs no migration. Another browser keeps its own choice.
- **No flash:** a short script in `web/index.html` sets `data-theme` on `<html>` before the stylesheet draws anything, so a reload never shows Charcoal first.
- **CSS:** each theme is one block at the top of `styles.css` (`:root[data-theme="gallery"]`, `:root[data-theme="midnight"]`) that redefines the color tokens. Charcoal is the plain `:root`. The token names stay as they were: `--amber` is each theme's action color and `--teal` its save and focus color.
- **Fixed colors removed:** the few colors that were written directly into the CSS are now tokens, so the light theme gets light versions:
  - `--overlay` and `--on-overlay`: chips and rating badges sitting on covers.
  - `--cover-edge` and `--cell-edge`: the hairline around covers.
  - `--backdrop`: behind the filter dialog.
  - `--map-dot` and `--map-dim`: the Album Map's dots.
- **Album Map:** it reads its colors from the tokens when it opens. A theme changed while the map is open shows there after the next visit to it.
- **Brand icons:** the Spotify and Apple Music icons keep their brand colors.

## Not covered
- **No "match the system" option.** A visitor whose device is in light mode still starts on Charcoal. That would be a fourth option if wanted.
- **Not on the server:** the choice isn't stored with the account, so it doesn't follow a signed-in visitor to a new browser.
