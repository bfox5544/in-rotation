# 0023: Import from Spotify

Status: **withdrawn** (2026-11-04). The owner doesn't have Spotify Premium, which Spotify's Development Mode requires of an app's owner, and asked for the feature to be removed the same day. The code was deleted, and migration 0010 drops `spotify_imports`. The rest of this record describes what was built, kept for reference. Options not taken: uploading Spotify's privacy data export ("Download your data"), or importing from Last.fm.

Original owner decisions:
- Log in with Spotify, not a file upload.
- Imported listening becomes **suggested ratings** that the user reviews before anything is saved. Ratings stay the only taste signal (ADR 0009).

## Flow
1. On `/import/spotify` the user presses Connect Spotify. `POST /api/spotify/connect` creates a single-use `state` and a PKCE verifier. It stores the state's SHA-256 hash and the verifier in `spotify_imports` (migration 0009, one row per user), then returns Spotify's authorize URL. The scopes are `user-library-read` and `user-top-read`.
2. Spotify sends the browser to **the API's** `GET /api/spotify/callback` at `http://127.0.0.1:8000/...`. Spotify no longer accepts `localhost` redirect URIs, so this has to be the loopback IP. That page has a different origin from the site, so the browser's session token isn't available there. Instead, the state names the user. It works once, and only within 15 minutes.
3. The callback exchanges the code (PKCE, no client secret) and reads three things:
   - Saved albums: up to 500, in pages of 50.
   - Top tracks for `long_term`, `medium_term` and `short_term`: 50 each.

   It matches what it finds to the catalog, stores the suggestions, drops the token, and redirects to `/import/spotify?spotify=ready`. The other outcomes are `denied` (cancelled, or not on the app's allowlist), `failed` and `expired`.
4. The user reviews the suggestions. They can untick albums or change stars. `POST /api/spotify/import` saves the chosen ratings, and the page moves on to For You. Discard (`DELETE`) throws the suggestions away.

The Spotify access token only exists while the callback runs. It is never stored or logged, and no refresh token is requested for later use. Only catalog album ids and the play signals behind each suggestion are kept, and only until the user saves or discards them.

## Matching (about 75 ms for a typical library)
1. **Spotify links from MusicBrainz:** the `album_links` table holds 164K catalog album ↔ Spotify album URLs, including edition releases. These are exact, and they point a deluxe edition at the regular album.
2. **Title and artist:** the title is passed through `norm(strip_edition(...))` with the dataset's own DuckDB macros (ADR 0003; normalization is never reimplemented in Python), plus `norm` of the first artist. These are compared with the catalog's `title_norm` and an `artist_norm` that starts with that artist. Albums of type Album and higher listener counts win ties.

Singles are left out. A spot check of 18 common Spotify titles against the real catalog matched 15, including `(Remastered)`, `(Super Deluxe)` and `- 50th Anniversary Remaster`. The three misses were unusual titles such as "Thriller 25 Super Deluxe Edition". A real import usually reaches those through step 1.

## Suggested stars
Spotify's API gives no play counts, so the signals are being saved and being among the top tracks.
- **Points:** a saved album gets 1. Each top track adds its time range's weight (all time 1.0, about 6 months 0.7, about 4 weeks 0.5), scaled from 1 at rank 1 down to 0.02 at rank 50. Editions that match the same album add up.
- **Stars:** 3+ points is 5 stars, 2+ is 4.5, 1.2+ is 4, and anything else is 3.5. Every suggestion is at least 3.5, because these are albums the user chose to play. All of them therefore count toward the recommendation query (3 stars and up).
- **Limit:** at most 200 suggestions are kept, best first.

These thresholds are a judgement call, not an experiment. The review step is there because they will sometimes be wrong.

## Rules
- An existing rating always wins. Already-rated albums are counted, not shown, and never overwritten.
- `POST /api/spotify/import` accepts only albums that are in that user's import (otherwise 422).
- Connecting again replaces an unfinished import. Signing in to an account drops an anonymous user's unsaved import (it is deleted with the anonymous user). Saved ratings merge as usual.

## Spotify's Development Mode (2026)
The site owner registers an app at developer.spotify.com and needs Spotify Premium. They add the redirect URI exactly, and put the client id in `backend/.env` as `SPOTIFY_CLIENT_ID`. Until Spotify reviews the app, only 5 allowlisted users can log in. Everyone else is refused by Spotify and comes back with `denied`, and the page explains why. Without a client id the feature is off: `/api/spotify/status` says so and the page shows the setup note.

## Not verified
No real Spotify login has been made, because no app is registered yet. The tests use a fake Spotify (`httpx.MockTransport`) that follows the documented response shapes. The review, save and For You steps were checked in a browser with an import built by the real matcher from typical Spotify titles.
