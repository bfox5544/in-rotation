# 0026: Filters on For You

Status: accepted (2026-11-09, owner request: "more filters (such as genre filter, time period filter) on the For You page").

## The control
For You has a **Filters** button beside its pick count, under the How Well Known slider. It opens the same dialog as Browse Albums (ADR 0015), titled Filter Your Picks, with:
- **Genre:** one searchable field. A genre includes its subgenres and fusions, as on Browse Albums.
- **Decade.**
- **Length:** Under 30 Minutes, 30 to 45 Minutes, 45 to 60 Minutes, or Over an Hour. For You only.
- **Album Type.**

Differences from Browse Albums:
- **No Exact Year or Country.** The first version had them; the owner removed them on 2026-11-09, when Length was added.
- **No Popularity field.** The How Well Known slider (ADR 0012) already does that job, and the two combine.
- **No count on the button.** It reads Show Picks, because counting picks means running the recommendation itself.

Applied filters show as removable chips with Clear All, as on Browse Albums. They live in the URL (`?genre=jazz&decade=1960`), so Back and shared links keep them, and applying them returns to page 1.

API: `GET /api/me/recommendations` takes `genre`, `year_from`, `year_to`, `country` and `type`, validated like `/api/albums`, and `length` (`under_30`, `30_45`, `45_60`, `over_60`; `catalog.LENGTHS`). The page no longer sends `country` or an exact year, but the API still accepts them. Old links carrying `year` or `country` are ignored by the page.
- **No match:** when the user's taste is known but nothing close to it passes the filters, the answer is an empty list with `source: "listening-data"`, and the page says to remove a filter.
- **Fallback:** the popularity fallback (no rating maps to the listening data) applies the filters too.

## Album length
An album's length is the sum of its track list (ADR 0013), the release the album page shows.
- **Unknown lengths:** about 5% of albums have a track without a time, so they have no length and match no band. Almost all well-known albums are timed: 3,151 of the 3,173 with 1,000+ listeners.
- **Singles and EPs** count by their length too, so Under 30 Minutes includes them. Combine it with Album Type, Studio Albums, for short albums only.
- **When it's worked out:** summing every track list takes about 9 seconds, so the API does it once in a background thread at startup (`Catalog.warm_lengths`) and keeps the four bands in memory (about 30 MB). A length request made in the first seconds after a restart waits for it. No catalog rebuild or new column was needed.
- **Speed:** on the full data, a length-filtered page takes 60-205 ms.
- **The fallback** for users whose ratings don't map to the listening data walks the popularity order for albums passing the filters (`Catalog.popular_among`).

## How it ranks: a wider neighbourhood
The filter keeps only albums passing it (`Catalog.filtered_ids`, passed to `Engine.recommend` as `only`). The usual ranking scores only albums held by the query's 100 nearest listeners (K 100, ADR 0004), and a filter can leave few of them:
- **Jazz:** 30 picks of 240 on average.
- **Jazz from the 1960s:** 2.
- Half of listeners can't fill even one page of 24 for jazz or the 1970s.

So **filtered lists rank by the 1,000 nearest listeners, and fill from the 5,000 nearest** if that still runs short (`FILTER_K` in `backend/app/engine.py`). The experiment (docs/experiments.md, run 5) compared three versions:
- **K 100 alone** misses many of the albums listeners love within the filter.
- **K 100 first, then filled from wider neighbourhoods,** finds them further down the list.
- **K 1000 from the start** does as well or better in both the top 24 and the whole list for every filter but two broad ones (hip hop, 2010s), where its top 24 is 0.01 to 0.02 lower, within noise.

Run 4 had already found K 500 the weakest for unfiltered lists (ADR 0004). A filter changes that, because the narrower the set of eligible albums, the more listeners it takes to cover it.

**"Because you rated"** (ADR 0021) uses the same 1,000 neighbours for filtered lists, so later picks are explained too.

**Speed:** on the full data, a filtered page takes 45-130 ms, and up to about 210 ms combined with a How Well Known step. The first use of a filter adds a few tens of milliseconds to collect its album ids. The last 16 filters' ids, and their excluded model albums, are kept.

## Limits
- **Tags decide genre membership.** An album's genre matches if any of its MusicBrainz tags is in the genre's family, so Jazz includes Portishead's Dummy (tagged acid jazz) and black midi's Hellfire (tagged jazz fusion). That's how Browse Albums works too (ADR 0015).
- **Small samples:** the narrow filters in the experiment had 35-57 test listeners each, and jazz in the 1960s had one, so their differences are rough.
- **Model terms:** the experiment was measured in model terms, without the artist cap or edition merging, as in ADR 0004.

## Revision (2026-11-10): item kNN (ADR 0028)
Item kNN scores every album, so a filter only narrows the full ranking, and the wider neighbourhoods (`FILTER_K`) are gone. The run 5 script now builds the old model itself.
