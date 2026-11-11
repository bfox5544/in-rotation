# 0011: Serve covers from a local cache

Status: accepted (2026-11-02), at the owner's request ("covers should appear instantly"). Changes ADR 0005's "linked from the Cover Art Archive, not re-hosted".

## Why
- **Each cover took 3-7 seconds.** The Cover Art Archive answers `release-group/{mbid}/front-250` with two redirects to archive.org, which is slow to serve the file.
- **Browsers can't cache the redirect**, so every visit paid the wait again.
- Nothing in the page could fix that. The bytes have to come from somewhere fast.

## How
- **`GET /api/covers/{album_id}`** (`backend/app/covers.py`) serves `data/covers/<2 chars>/<mbid>.jpg` from disk with `Cache-Control: max-age=30 days`. `Album.coverUrl` now points there.
  - **A hit takes about 10 ms**; after that the browser's own cache answers.
  - **On a miss**, the API fetches the image from the archive once (3-7 s), stores it atomically and serves it. Simultaneous requests for the same cover share one fetch.
  - **No archived art** is a 404, remembered for a week with a `.none` marker, after which the archive is asked again. The page shows generated artwork for those albums.
  - **An archive failure** (timeout, 5xx) is a 502 marked `no-store`. Nothing is cached, so the next view retries.
  - Only catalog album ids are accepted, so the endpoint can't be used to fetch arbitrary archive content. Ids merged by MusicBrainz resolve through `album_redirects`.
- **`python -m ingest.covers --top N`** pre-fetches the most-listened albums not yet cached, using 8 parallel downloads. Discover, search and recommendations lean heavily on popular albums, so most covers people see are already on disk.
  - **First run, `--top 5000`:** 29 minutes, 4,933 covers stored (118 MB), 17 albums with no archived art, and 50 archive failures left after one retry, to be fetched on first view.
  - The top 5,000 albums account for 59% of listening, and 80% of the covers on a sample of Discover, search and For you pages were already cached.
  - **Extended to `--top 20000`** (78% of listening): 79 minutes, 14,341 more covers, 138 albums with no archived art, 558 archive failures. A second pass with 4 workers recovered 418 of them. The cache is 482 MB with 19,758 covers; about 85 of the top 20,000 are left to be fetched on first view. Reruns skip what is cached, so an interrupted run resumes.
  - The top 50,000 would reach 88%.
  - Rerun it after a catalog refresh to fetch covers for new albums.
- **The page** keeps a neutral tile in place and fades the image in when it arrives, instead of popping in. Reduced-motion settings turn the fade off.

## Costs and caveats
- **Disk:** about 35-40 KB per cover, so roughly 200 MB per 5,000 albums. It lives under `data/` (git-ignored).
- **Licensing:** cover art belongs to its copyright holders, and the Cover Art Archive does not license it. Keeping cached copies for this non-commercial portfolio project is a reasonable use. **Review it with the dataset licence before any public deployment.** The footer still credits the Cover Art Archive.
- A first-ever view of an uncached album still waits for the archive once.
- **M9:** put a CDN in front of `/api/covers`; its 30-day cache headers already suit one.
