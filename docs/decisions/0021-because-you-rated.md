# 0021: "Because You Rated" on For You

Status: accepted (2026-11-03). The owner picked it from a list of user experience improvements.

## What it shows
Each For You card gets a third caption line, for example "Because you rated folklore and IGOR". It names up to two of the user's own rated albums and is cut to two lines. It isn't a link. The album page already has the full match explanation (ADR 0019).

## How the albums are chosen (`Engine.explain`, field `telling`)
The query is the same as for For You: ratings of 3 stars and up, weighted by stars, through the 100 nearest historical listeners. For each recommended album and each rated album ("seed"):

- `shared` = the neighbours who have both the recommended album and the seed.
- `fans` = the neighbours who have the seed.

Seeds are ranked by **`shared / fans`**, the share of the seed's fans among the neighbours who also have the album. A seed needs at least `TELLING_MIN` = 3 shared neighbours before it can count. The top two are shown.

### Why not the raw `shared` count
The existing `seeds` field ranks by the raw count. Ask uses it, and it stays as it is. As a "because" line it fails: the neighbours are chosen *for* holding the user's albums, so the one nearly all of them hold wins almost every time.

One trial used a throwaway taste of the 12 most-listened albums, over the first 72 recommendations:
- Ranked by raw count, Ultraviolence was named 52 times and Norman Fucking Rockwell! 32 times. Five of the 12 rated albums were named once or never.
- Ranked by share, every rated album was named 3 to 25 times. The pairs also read better: Starboy came from Born to Die and channel ORANGE, Hatful of Hollow from AM and The Bends, and Punisher from folklore and Blonde.

This is a single trial, not an evaluation. The line describes listener overlap. It doesn't claim to be the engine's actual scoring path.

## API
`GET /api/me/recommendations` gains `because: {album id: [rated album id, ...]}` (at most 2 each). It is empty for the popularity fallback. The frontend turns the ids into titles from the library it has already loaded. Counts only: historical users are never identified.

## Cost
About 25-30 ms more per page on full data (60-85 ms a page, up from about 40-55 ms), since `explain` finds the neighbours a second time. Caching the neighbours between `recommend` and `explain` would remove this if it ever matters.

## Revision (2026-11-10): item kNN (ADR 0028)
With item kNN, a pick's score is a sum over the rated albums, so each one's share is exact (`Engine.explain`, `seeds`). Named first by share alone, a central album (Kid A in a test taste) explained most cards. `telling` now keeps the seeds carrying at least 15% of the score (`TELLING_SHARE`) and orders them by how much closer the pick is to them than the rest of the page is.
