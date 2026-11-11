# 0016: Spotify and Apple Music links on album pages

Status: accepted (2026-11-03, owner requests).
- **"Add links to Spotify and Apple Music"**, then **"make it automatically open to the album page rather than searching"**.
- **"It should always open to the regular version, not a deluxe or other version."**

## How a link is chosen
The album page links to `GET /api/albums/{id}/listen/{spotify|apple-music}` (`app/listen.py`), a 302 redirect.

On the page (`components/StreamingLinks.tsx`) they are two icons after a small "Listen On" label (owner request, 2026-11-03): the Spotify and Apple Music marks in their brand colours, drawn as simple solid SVGs, 40px round hit areas. Each has the service name as a tooltip and "Open <album> on <service> (new tab)" as its accessible name.

**1. Candidates, offline (`ingest.catalog.streaming_links()`).**
- **Source:** MusicBrainz URL relationships, from the core-dump tables `url`, `l_release_url` and `l_release_group_url`. They are in the README extract command and `ingest.refresh --core`.
- **What's kept:** up to 5 links per album and service in `album_links` (catalog `schema_version` 7), each with an **edition hint**.
- **Why a hint is needed:** MusicBrainz files reissues under the original album ("Illmatic XX", "OK Computer OKNOTOK 1997 2017"). A release's hint is the worst of three checks:

  | Check | Regular | Remaster | Other edition |
  |---|---|---|---|
  | Title | the album's own | the album's plus a remaster tag | anything else |
  | Disambiguation note | no edition words | mentions a remaster | deluxe, expanded, anniversary and similar |
  | Audio track count | standard edition's | (n/a) | more than the standard edition (the track list's release, ADR 0013) |

  A link on the release group itself counts as regular.
- **Ranking:**
  1. hint
  2. Apple links valid in every store first
  3. the track list's release, the group's link, the oldest official release, the oldest release
- **Apple country codes:** a US-store (or unmarked) id is linked without a country, so it opens in the listener's own store. An id known only from another country's store keeps that country, because the album may not exist elsewhere.
- **Coverage:** 141,575 albums have Spotify candidates and 144,352 have Apple ones, about 77% and 76% of listening.

**2. Checking, on first click.**
- **The hint is often wrong in both directions:** a release with bonus tracks may still be plain "4" on Spotify, and a quarter of stored Apple links were dead.
- **Each service's own title for the album is the judge,** fetched through public, keyless endpoints:
  - Spotify: oEmbed (`open.spotify.com/oembed`)
  - Apple: iTunes lookup, checked in the link's own store
- **How a title is classed:**

  | Class | Examples |
  |---|---|
  | The album itself | ignoring spacing, punctuation and Apple's " - Single"/" - EP"; a `*` stands for a censored letter ("Songs About F*****g") |
  | A remaster or mono/stereo mix | "Abbey Road (Remastered 2009)", "Pet Sounds (Original Mono & Stereo Mix)" |
  | Another edition | deluxe, expanded, anniversary, live, version… |
  | A different title | "Illmatic XX" |
- **Which candidate wins:** up to 4 are checked. The first that is the album itself wins; else the first remaster. Another edition or a different title is **never** used.
- **Apple fallback:** with no good candidate, Apple's search API (keyless) is asked for the album itself, or a remaster, by the same artist.

**3. Otherwise, the service's search page** for title and artist. That's also the outcome when a service only carries other editions.

**Caching and outages:**
- Answers are cached in memory for a week, or a day for a search page.
- If a service's API can't be reached, MusicBrainz's best regular-hinted candidate is used (or the search page), and nothing is cached.

## Measured live (2026-11-03)
I tested 15 well-known albums that have deluxe editions or reissues.

- **No deluxe or reissue editions opened.** OK Computer, Illmatic and Kid A open the originals, not OKNOTOK, Illmatic XX or the deluxe sets. Abbey Road opens its remaster on both services. Pet Sounds opens Spotify's "Original Mono & Stereo Mix".
- **Search pages where the service only carries other editions:**
  - Apple only has "4 (Expanded Edition)" and "E=MC2 (Deluxe Version)".
  - Spotify only has "Born Sinner (Deluxe Version)".
  - MusicBrainz only links the deluxe St. Vincent and Franz Ferdinand albums on Spotify.
  - Apple's search returned nothing usable for "Nevermind".
- **Speed:** the first click takes 0.1–1 s, and up to 4 s when several Spotify candidates are dead. Later clicks are instant.
- **Spotify gaps:** without Spotify's own (keyed) Web API, an album whose Spotify candidates are all other editions can't be found. It gets the search page.

## Why not the services' own APIs
- **Spotify's Web API** needs a developer account and client credentials, which would be a new external service. The owner hasn't been asked to add one.
- **Apple's iTunes APIs and Spotify's oEmbed** are public and keyless, like the Cover Art Archive (ADR 0011). They're called only when someone follows a link, at most about 5 requests per album and service per week.

## Limits
- The cache starts empty after each API restart.
- Apple's search runs on the US store.
- An album a service only offers as a deluxe or other edition opens that service's search page, by the owner's rule.
