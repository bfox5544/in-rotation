# 0010: Rating badges on covers, and dismissing albums from For you

Status: accepted (2026-11-02), at the owner's request.

## Rating badge
- **Every album cover has a badge in the top-left corner.** It shows "★ 4½" when the album is rated and "☆ Rate" when it isn't.
- **Clicking the badge opens a small star selector** on the cover (`RatingBadge.tsx`). It reuses the half-star slider from ADR 0009, so mouse, touch and keyboard behave the same everywhere.
- **The selector closes** after a click on the stars, Enter, Escape (focus returns to the badge) or a click elsewhere.
- Album pages keep their full-size stars. Onboarding keeps stars under each cover.

## Dismissing from For you
- **An X in the top-right corner of each For you album** removes it. It never comes back on For you, for this user, on any browser once signed in.
- The list refills from the server to its usual length, and an "Undo" stays visible for 6 seconds.
- **Storage:** `user_dismissals(user_id, album_id, created_at)`, Alembic migration 0004. The API is `PUT`/`DELETE /api/me/dismissed/{album_id}`, and the delete is the undo.
- Dismissals follow MusicBrainz merges (ADR 0007), apply to the popularity fallback too, and move into an account on sign-in.
- **A dismissal is only an exclusion, not a dislike signal.**
  - "Not now" or "already know it" are as likely as "dislike", and the data can't tell these apart; this is the same reasoning as for low ratings (ADR 0008).
  - Rating the album below 3 stars is the way to say "not for me".
- **No page lists dismissed albums yet,** so after the undo window, the only way to bring one back is through the API.
