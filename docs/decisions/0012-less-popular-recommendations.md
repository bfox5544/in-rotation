# 0012: Less popular recommendations on For you ("How well known?")

Status: proposed (2026-11-02, owner request: "a slider or option on For you to find albums they will like that are less popular").

## The control
For you has a four-step slider, **How well known?**, that sets the largest number of listeners a suggestion may have. The numbers are listeners in the listening data, out of about 476,000.

| Step | Label | Listeners |
|---|---|---|
| 0 | Anything | no limit (the served ranking, unchanged) |
| 1 | Less known | under 5,000 |
| 2 | Under the radar | under 1,000 |
| 3 | Deep cuts | 10 to 200 |

- The API takes `GET /api/me/recommendations?depth=0..3`. The caps are `LISTENER_CAPS` in `backend/app/engine.py`.
- "Listeners" is the catalog album's `popularity`: model listeners summed over its editions.
- The browser remembers the step in `localStorage` (`inrotation.depth`). It is a per-browser display preference, not part of the account.
- When no rating maps to the listening data, the popularity fallback also respects the cap.

## How it ranks: a cap, not a stronger dampener
The served ranking already divides scores by popularity^0.25 (ADR 0004). The obvious slider would raise that exponent. The experiment (docs/experiments.md, run 3; `python -m recs.less_popular`) rules that out:
- **A stronger dampener collapses into noise.** At beta 0.5 the median suggestion has 6 listeners, and at 1.0 it has 2. Albums that one neighbour happens to own float to the top. Recall of the less known albums users actually loved falls by 40% to 97% against the capped ranking.
- **A listener cap on the normal ranking** finds 1.3–2× more of them than the uncapped ranking at every cap.
- **Inside a cap, the dampener hurts.** It pushes suggestions toward albums with a handful of listeners. Turning it off raises recall at the 1,000 and 200 caps (0.152 → 0.161 and 0.103 → 0.119) and leaves 5,000 unchanged.
- **A floor of 10 listeners** removes the remaining 2–9-listener suggestions. In the live smoke test those were obviously odd, such as a 2-listener box set. The cost is about 3% recall at the 200 cap, which is a deliberate product trade-off.

So under a cap the engine ranks with `pop_beta=0` (`Recommender.reconfigure`, sharing the fitted matrix) and excludes albums outside `MIN_LISTENERS..cap` before ranking. Each cap's exclusion list is built on first use (about 0.2 s) and kept, after which a capped request takes 15-20 ms, the same as an uncapped one.

## Limits
- "Deep cuts" is the least certain step. Only 1 in 5 to 3 in 10 users get a hit in their top 20, against 6 to 7 in 10 at "Less known". The lists are more varied and, by design, more of a gamble.
- Listener counts come from a snapshot of one site's users and lean toward its audience, so "under the radar" means under the radar there.
- The artist cap (2 per artist) and alias merging still apply but were not part of the experiment, as in ADR 0004.

## Revision (2026-11-10): item kNN (ADR 0028)
Item kNN ranks with no popularity adjustment at every step, so "β 0 under a cap" is now simply the ranking. The caps and the 10-listener floor were checked again on item kNN (run 7) and kept. Under the Radar finds 0.240 of loved albums under 1,000 listeners on full queries against 0.104 uncapped, and 0.153 against 0.073 on 10-album queries.
