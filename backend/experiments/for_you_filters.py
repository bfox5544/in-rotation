"""For You filters: held-out albums found, with each listener left out of their own neighbours.

In model terms (no artist cap or edition merging). 80% of a historical listener's albums are the query; the
held-out 20% that pass the filter are the targets. Compares:
  k100    - K 100 only (the usual neighbourhood: what an unfiltered list cut down to the filter would give)
  staged  - K 100 first, then filled from K 1000, then K 5000
  k1000   - K 1000, filled from K 5000 (chosen then, as engine.FILTER_K)
Counts only; no historical user is identified. docs/experiments.md run 5, ADR 0026. This tested the user kNN
model the site served until 2026-11-10. Item kNN scores every album, so a filter only narrows its ranking and
needs no wider neighbourhood (ADR 0028); the script builds the old model itself to stay reproducible.
Run from backend/ (about 2 minutes on the full data): PYTHONPATH=.:.. python experiments/for_you_filters.py
"""
from collections import defaultdict

import numpy as np

from app import engine as E
from app.catalog import get_catalog
from recs.query import query_vector
from recs.recommender import Recommender

cat = get_catalog()
eng = E.get_engine()
rec = Recommender.from_model_dir(E.model_dir())
rng = np.random.default_rng(11)

FILTERS = {
    "jazz": dict(genre="jazz"), "hip hop": dict(genre="hip hop"), "metal": dict(genre="metal"),
    "1970s": dict(year_from=1970, year_to=1979), "2010s": dict(year_from=2010, year_to=2019),
    "jazz 1960s": dict(genre="jazz", year_from=1960, year_to=1969),
    "electronic 1990s": dict(genre="electronic", year_from=1990, year_to=1999),
    "folk 2000s": dict(genre="folk", year_from=2000, year_to=2009),
}
N_USERS, WANT, OVER = 400, 240, 5
R = rec.R
users = rng.choice(np.flatnonzero(np.diff(R.indptr) >= 20), N_USERS, replace=False)
outside = {name: eng._outside(cat.filtered_ids(**f)) for name, f in FILTERS.items()}
allowed = {}
for name, out in outside.items():
    m = np.ones(rec.n_albums, bool)
    m[out] = False
    allowed[name] = m


def ranked(q, u, k, exclude):
    idx, sim = rec.neighbours(q, k=k + 1)
    keep = idx[0] != u                                   # leave the listener out of their own neighbours
    idx, sim = idx[:, keep][:, :k], sim[:, keep][:, :k]
    scores = rec.score(idx, sim)[0]
    scores[exclude] = 0
    m = min(WANT * OVER, int((scores > 0).sum()))
    if m == 0:
        return np.empty(0, np.int64)
    part = np.argpartition(-scores, m - 1)[:m]
    return part[np.argsort(-scores[part], kind="stable")]


def staged(q, u, exclude, ks):
    out = []
    for k in ks:
        for a in ranked(q, u, k, exclude):
            if a not in out:
                out.append(a)
            if len(out) == WANT:
                return out
    return out


stats = defaultdict(lambda: defaultdict(list))
for u in users:
    models = R.indices[R.indptr[u]:R.indptr[u + 1]]
    models = models[eng.shown[models]]                   # albums the site can show
    if len(models) < 10:
        continue
    models = rng.permutation(models)
    cut = int(len(models) * 0.8)
    query, held = models[:cut], models[cut:]
    q = query_vector(list(query), rec.n_albums, [1.0] * len(query))
    for name in FILTERS:
        targets = set(held[allowed[name][held]])
        if not targets:
            continue
        ex = np.concatenate([query, outside[name]])
        for label, ks in (("k100", (100,)), ("staged", (100, 1000, 5000)), ("k1000", (1000, 5000))):
            got = staged(q, u, ex, ks)
            stats[name][f"{label}@24"].append(len(targets & set(got[:24])) / len(targets))
            stats[name][f"{label}@240"].append(len(targets & set(got)) / len(targets))
            stats[name][f"{label}_len"].append(len(got))

print(f"{len(users)} listeners sampled; recall of held-out albums passing the filter, in the first 24 and in all 240")
print(f"{'filter':18} {'users':>5} | {'K100 @24':>8} {'@240':>5} {'len':>4} | {'staged @24':>10} {'@240':>5} {'len':>4} | {'K1000 @24':>9} {'@240':>5}")
for name in FILTERS:
    s = stats[name]
    m = lambda k: np.mean(s[k])
    print(f"{name:18} {len(s['k100@24']):>5} | {m('k100@24'):8.3f} {m('k100@240'):5.3f} {m('k100_len'):4.0f} | "
          f"{m('staged@24'):10.3f} {m('staged@240'):5.3f} {m('staged_len'):4.0f} | {m('k1000@24'):9.3f} {m('k1000@240'):5.3f}")
