# 0020: Footer, Contact, Data Sources, How Recommendations Work

Status: accepted (2026-11-03, owner request).

## Footer
- **One component** (`web/src/components/Footer.tsx`), rendered once by `App` below `<main>`, so it is on every page, including 404s.
- **Contents:**
  - the In Rotation wordmark and © the current year
  - three links: Contact, Data Sources and How Recommendations Work
  - ~~a small credit line for MusicBrainz, the Cover Art Archive and the listening dataset~~ (removed 2026-11-04 at the owner's request. The Data Sources page, linked from every footer, credits all three.)
- **Style:**
  - a hairline above, soft text, and the same 1px amber underline as the header for the current page
  - stacked on phones
- **Layout:** `#root` is a flex column, so on short pages the footer sits at the bottom of the window. It is never fixed or sticky, so it can't cover content. The sticky bars on Onboarding and Ask stay inside `<main>`.
- **Scrolling:** the app keeps the scroll position between pages, so footer links scroll to the top themselves. Other navigation is unchanged.

## Pages
- **`/contact`:**
  - a feedback form: topic, message (up to 2,000 characters), optional email for a reply
  - a note that album details can be fixed at MusicBrainz
  - a public contact address only if `VITE_CONTACT_EMAIL` is set in `web/.env` at build time. The owner's address was not put on the site without asking.
- **`/data-sources`:**
  - the listening dataset, [Music Listening Data (~500k Users)](https://www.kaggle.com/datasets/gabrielkahen/music-listening-data-500k-users) by Gabriel Kahen on Kaggle, with what cleaning keeps
  - MusicBrainz (dumps, CC0 core data, CC BY-NC-SA genres and tags)
  - the Cover Art Archive
  - how streaming links are checked
  - what the Ask assistant sends to Google
- **`/how-recommendations-work`:**
  1. the dataset
  2. rank and play weights (formula and a table)
  3. star weights
  4. cosine similarity
  5. collaborative filtering
  6. the popularity adjustment (÷ listeners^0.25) and the How Well Known slider
  7. match scores
  8. the evaluation in plain words (about 9x the popularity baseline, NDCG@20 0.24 vs 0.026; about 4x with 3 albums)
  9. limits

  The numbers are the ones in ADRs 0003, 0004, 0008, 0012 and 0019. Change both together.
- **Shared layout:** the pages use `components/InfoPage.tsx` (title, lead, sections) and follow the site rules: Title Case headings, no semicolons, full-width text.

## Feedback storage (migration 0008)
- **Table:** `feedback(id, user_id → users ON DELETE SET NULL, topic, message, reply_to, created_at)`.
- **Route:** `POST /api/feedback` (session needed) returns 204.
  - **Topics:** feedback, recommendations, data, bug, other.
  - **Validation:** 422 for an empty or overlong message or a bad reply email.
  - **Limit:** 429 after 5 messages an hour per browser.
- **Reading it:** there are no admin accounts, so the owner reads messages with `python -m app.feedback [--limit N]` from `backend/`.
- **Reply emails** are stored only to answer and are never shown.

## Licensing
The dataset's Kaggle page could not be read without signing in, so **its licence is still unverified**. The Data Sources page credits it without claiming a licence. This stays on the pre-deployment licensing review.

## Revision (2026-11-10): Privacy page, self-hosted fonts
Before the site goes public without a password, a **Privacy** page (`/privacy`, `pages/Privacy.tsx`, linked from the footer) says what's kept (anonymous libraries, accounts, Contact messages), what isn't (no analytics, ads, trackers or cookies, addresses only as keyed hashes for up to two days), who else sees it (Cloudflare, OVHcloud, Google for Ask only), browser storage, how long things are kept (account until deleted, anonymous libraries 7 days or a year, 14-day backups) and how to ask for a copy or deletion (the Contact page). To make "your browser doesn't contact anyone else" true, the two fonts are now served from the site (`web/public/fonts`, about 210 KB, SIL Open Font License) instead of Google Fonts. Visitors also no longer see developer hints: a stopped API says "In Rotation can't be reached right now" and Ask without a key says it isn't available (the old hints stay in `npm run dev`).
