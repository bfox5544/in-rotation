"""Recommendations from the listening-data engine (recs/), served in catalog terms.

The model is item-based collaborative filtering (recs.item_knn, since 2026-11-10: docs/experiments.md
runs 6 and 7). Loaded once at startup: the listener x album weight matrix is built and its album
columns scaled to length 1 (a few seconds, about 1 GB for the full dataset); each request scores
every album by its summed cosine similarity to the user's rated albums (two sparse products, tens of
milliseconds), and recent queries' scores are cached because For You, its explanations and the match
score all reuse them.

Catalog ids (release-group MBIDs) map to model album indexes through album_id_map. Several
model albums can map to one catalog album (editions, artist aliases); all of them go into the
query, and their recommendations collapse back to one catalog album. Model albums with no
catalog match still link listeners to albums but are never shown. ADR 0005 and 0028.
"""
import logging
import os
import threading
from collections import OrderedDict, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from recs import match as match_score
from recs.item_knn import DIVERSE_POOL, ItemKNN, diversify
from recs.query import query_vector

from .catalog import REPO, Catalog, get_catalog

log = logging.getLogger(__name__)

OVERFETCH = 5        # model candidates per requested album: absorbs unmapped albums, merges and the artist cap
ARTIST_CAP = 2       # at most this many albums by one primary artist in a list
ARTIST_SEEDS = 5     # an artist's most-listened albums that stand for the artist in related_artists
# For you "depth": the most listeners (of 476K in the listening data) an album may have at each step,
# skipping albums under MIN_LISTENERS. Item kNN ranks without a popularity adjustment at every step.
# Chosen in run 3 and checked again on item kNN in run 7 (ADR 0012).
LISTENER_CAPS = (None, 5000, 1000, 200)
MIN_LISTENERS = 10
# Match score (ADR 0019, revised for item kNN in run 7): an album's percentile among the albums held by at
# least MATCH_SHARE of the listeners who have one of the user's albums (and MATCH_MIN_SUPPORT of them).
MATCH_SHARE = 0.001  # 0.1%: the most loved albums scored and the sharpest split of the shares tried (run 7)
MATCH_MIN_SUPPORT = 3
# A small album can't reach MATCH_SHARE of a big audience (0.1% of 100,000 is more than a Deep Cut's whole
# audience), so it needs that share or OWN_SHARE of its own listeners, whichever is fewer (run 9).
OWN_SHARE = 0.05
# Thinly held albums (ADR 0028, run 7): with few rated albums, cosine favours albums with 2-3 listeners who all
# share them. SUPPORTED_ONLY keeps only albums the match score can score (the support rule, `_need`), so every
# pick has one, and FLOOR is a least listener count for every list.
SUPPORTED_ONLY = True
FLOOR = 10
SCORE_CACHE = 32     # recent queries' scores (~2.5 MB each, plus co-listener counts for match scores)
OUTSIDE_CACHE = 16   # For You filters' excluded albums (ADR 0026)
TELLING_SHARE = 0.15  # least part of an album's score a seed must carry to be named in "Because you rated"


def model_dir() -> str:
    return os.environ.get("INROTATION_MODEL_DIR", str(REPO / "data" / "model"))


class Engine:
    def __init__(self, model_path: str, catalog: Catalog) -> None:
        if not (Path(model_path) / "interactions.parquet").exists():
            raise RuntimeError(f"Model files not found in {model_path}. Run python -m recs.preprocess first (see README).")
        self.catalog = catalog
        self.model = ItemKNN.from_model_dir(model_path)
        mapped = catalog._query("SELECT model_idx, album_id FROM album_id_map WHERE album_id IS NOT NULL")
        if len(catalog._query("SELECT 1 FROM model_albums")) != self.model.n_albums:
            raise RuntimeError("catalog.db was built from a different model. Rebuild it with python -m ingest.catalog.")
        self.album_of = np.full(self.model.n_albums, None, dtype=object)
        self.models_of: dict[str, list[int]] = defaultdict(list)
        for row in mapped:
            self.album_of[row["model_idx"]] = row["album_id"]
            self.models_of[row["album_id"]].append(row["model_idx"])
        rows = catalog._query("SELECT id, primary_artist_id, popularity FROM albums")
        self.artist_of = {r["id"]: r["primary_artist_id"] for r in rows}
        self.listeners = {r["id"]: r["popularity"] for r in rows}
        self._outside_cap: dict[int, np.ndarray] = {}
        self.shown = np.array([a is not None for a in self.album_of])     # model albums the site can show
        self._lock = threading.Lock()                                     # requests run in a thread pool
        self._scores: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._support: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()
        self._outside_only: OrderedDict[frozenset, np.ndarray] = OrderedDict()

    def outside_cap(self, cap: int) -> np.ndarray:
        """Model albums whose catalog album has more than `cap` or fewer than MIN_LISTENERS listeners;
        dropped before ranking."""
        if cap not in self._outside_cap:
            self._outside_cap[cap] = np.array([m for a, ms in self.models_of.items()
                                            if not MIN_LISTENERS <= self.listeners.get(a, 0) <= cap for m in ms], dtype=np.int64)
        return self._outside_cap[cap]

    def _model_ids(self, album_ids) -> list[int]:
        return [m for a in album_ids for m in self.models_of.get(a, ())]

    def _seeds(self, seeds: list[str] | dict[str, float]) -> tuple[dict[str, float], list[tuple[int, float]]]:
        """({current album id: weight}, [(model index, weight)]) for a list or {album id: weight}."""
        weight: dict[str, float] = {}
        for album_id, w in (seeds.items() if isinstance(seeds, dict) else ((s, 1.0) for s in seeds)):
            current = self.catalog.canonical([album_id])[0]
            weight[current] = max(w, weight.get(current, 0.0))
        return weight, [(m, w) for a, w in weight.items() if w > 0 for m in self.models_of.get(a, ())]

    def knows(self, seeds: list[str] | dict[str, float]) -> bool:
        """Whether any seed maps to the model, so `recommend` has a query to rank by."""
        return bool(seeds) and bool(self._seeds(seeds)[1])

    def _cached(self, cache: OrderedDict, key, make):
        with self._lock:
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
        value = make()
        with self._lock:
            cache[key] = value
            while len(cache) > SCORE_CACHE:
                cache.popitem(last=False)
        return value

    def _query(self, picks: list[tuple[int, float]]):
        return query_vector([m for m, _ in picks], self.model.n_albums, [w for _, w in picks])

    def scores(self, picks: list[tuple[int, float]]) -> np.ndarray:
        """Every model album's score for this query, kept for the last SCORE_CACHE queries (read-only)."""
        key = tuple(sorted(picks))
        return self._cached(self._scores, key, lambda: self.model.scores(self._query(list(key)))[0])

    def recommend(self, seeds: list[str] | dict[str, float], exclude: set[str] = frozenset(), n: int = 24,
                  artist_cap: int | None = ARTIST_CAP, max_listeners: int | None = None,
                  only: frozenset[str] | None = None, diverse: bool = False) -> list[str]:
        """Catalog ids, best first. `diverse` (For You's Diversify, run 8) re-ranks the best DIVERSE_POOL
        candidates by maximal marginal relevance, so each pick is also unlike the ones before it; the rest
        follow in score order. `seeds` is a list (weight 1.0 each) or {album id: weight}, for
        rating-scaled queries (recs.ratings). `max_listeners` (one of LISTENER_CAPS) keeps only albums
        with MIN_LISTENERS up to that many listeners. `only` keeps only these catalog ids (For You
        filters, Catalog.filtered_ids): item kNN scores every album, so a filter only narrows the ranking.
        Empty when no seed maps to the model (the caller decides the fallback)."""
        weight, picks = self._seeds(seeds)
        exclude = self.catalog.canonical(list(exclude))
        if len(picks) < len(weight):
            log.info("%d of %d seeds have no model album", sum(1 for s in weight if s not in self.models_of), len(weight))
        if not picks:
            return []
        hidden = set(weight) | set(exclude)
        excluded = [np.array(self._model_ids(hidden), dtype=np.int64), self._thin(picks)]
        if max_listeners is not None:
            excluded.append(self.outside_cap(max_listeners))
        if only is not None:
            excluded.append(self._outside(only))
        scores = self.scores(picks)
        candidates, _ = self.model.recommend(self._query(picks), n=n * OVERFETCH, exclude=np.concatenate(excluded),
                                             scores=scores)
        if diverse:
            key = ("diverse", tuple(sorted(picks)), hash(candidates[:DIVERSE_POOL].tobytes()))
            head = self._cached(self._scores, key, lambda: diversify(self.model, candidates[:DIVERSE_POOL], scores, DIVERSE_POOL))
            candidates = np.concatenate([head, candidates[DIVERSE_POOL:]])
        out, per_artist = [], defaultdict(int)
        for album_id in self.album_of[candidates]:
            if album_id is None or album_id in hidden or album_id in out:
                continue
            artist = self.artist_of.get(album_id)
            if artist_cap is not None and artist and per_artist[artist] >= artist_cap:
                continue
            per_artist[artist] += 1
            out.append(album_id)
            if len(out) == n:
                break
        return out

    def _outside(self, only: frozenset[str]) -> np.ndarray:
        """Model albums whose catalog album isn't in `only`, kept for the last OUTSIDE_CACHE filters."""
        with self._lock:
            if only in self._outside_only:
                self._outside_only.move_to_end(only)
                return self._outside_only[only]
        keep = np.zeros(self.model.n_albums, dtype=bool)
        for album_id in only:
            keep[self.models_of.get(album_id, ())] = True
        outside = np.flatnonzero(~keep)
        with self._lock:
            self._outside_only[only] = outside
            while len(self._outside_only) > OUTSIDE_CACHE:
                self._outside_only.popitem(last=False)
        return outside

    def _similarities(self, weight: dict[str, float], album_ids: list[str]) -> tuple[list[str], np.ndarray]:
        """(seed ids, cosine similarity seeds x albums): editions of a seed add up, as in the query, and an
        album takes its best-scoring edition."""
        seeds = [a for a in weight if a in self.models_of and weight[a] > 0]
        cols = [m for a in album_ids for m in self.models_of[a]]
        if not seeds or not cols:
            return seeds, np.zeros((len(seeds), len(album_ids)))
        sim = self.model.similarity([m for a in seeds for m in self.models_of[a]], cols)
        rows = np.add.reduceat(sim, np.cumsum([0] + [len(self.models_of[a]) for a in seeds[:-1]]), axis=0)
        return seeds, np.maximum.reduceat(rows, np.cumsum([0] + [len(self.models_of[a]) for a in album_ids[:-1]]), axis=1)

    def _contributions(self, weight: dict[str, float], album_id: str) -> list[tuple[float, str]]:
        """(share of the album's score, seed id) per seed album, largest first: score(b) is a sum over the
        query albums of q(a) * cos(a, b), so each seed's part of it is exact."""
        seeds, sim = self._similarities(weight, [album_id])
        parts = [weight[a] * float(sim[i, 0]) for i, a in enumerate(seeds)]
        total = sum(parts)
        return sorted(((p / total, a) for p, a in zip(parts, seeds) if p > 0), key=lambda x: -x[0]) if total > 0 else []

    def explain(self, seeds: list[str] | dict[str, float], album_ids: list[str]) -> dict[str, dict]:
        """Why each album came up for the query `recommend` was given (ADR 0014, 0021): its score, how many
        listeners who have one of the query albums also have it, and the seed albums its score comes from
        (`seeds`: (id, share of the score), largest first, up to 3). `telling` (For You's "Because you rated")
        ranks the seeds that carry at least TELLING_SHARE of the score by how much closer the album is to them
        than the other albums asked about are: a seed close to everything, like a central, much-loved album,
        would otherwise explain every card. Counts only; historical users are never identified."""
        weight, picks = self._seeds(seeds)
        if not picks:
            return {}
        scores = self.scores(picks)
        support, holders = self._support_of(picks)
        ids = [a for a in dict.fromkeys(self.catalog.canonical(album_ids)) if self.models_of.get(a)]
        names, sim = self._similarities(weight, ids)
        w = np.array([weight[a] for a in names])[:, None]
        parts = w * sim
        share = parts / np.maximum(parts.sum(axis=0, keepdims=True), 1e-12)
        lift = sim / np.maximum(sim.mean(axis=1, keepdims=True), 1e-12)
        out = {}
        for j, album_id in enumerate(ids):
            models = self.models_of[album_id]
            order = [i for i in np.argsort(-share[:, j], kind="stable") if share[i, j] > 0]
            telling = sorted((i for i in order if share[i, j] >= TELLING_SHARE), key=lambda i: -lift[i, j])
            out[album_id] = {"score": float(scores[models].max()), "listeners": holders,
                             "listeners_with_album": int(support[models].max()),
                             "seeds": [(names[i], round(float(share[i, j]), 3)) for i in order[:3]],
                             "telling": [names[i] for i in telling[:3]]}
        return out

    def _thin(self, picks: list[tuple[int, float]]) -> np.ndarray:
        """Model albums too thinly held to recommend for this query (SUPPORTED_ONLY, FLOOR)."""
        drop = self.model.popularity < FLOOR
        if SUPPORTED_ONLY:
            support, holders = self._support_of(picks)
            drop = drop | (support < self._need(holders, self.model.popularity))
        return np.flatnonzero(drop)

    @staticmethod
    def _need(holders: int, listeners):
        """Least co-listeners for an album with `listeners` listeners to count as supported (run 7, run 9):
        MATCH_SHARE of the `holders` (listeners who have a query album), or OWN_SHARE of its own listeners if
        that is fewer, and never under MATCH_MIN_SUPPORT."""
        return np.maximum(MATCH_MIN_SUPPORT, np.minimum(MATCH_SHARE * holders, OWN_SHARE * np.asarray(listeners, float)))

    def _support_of(self, picks: list[tuple[int, float]]) -> tuple[np.ndarray, int]:
        """(co-listener count per model album, listeners holding a query album), cached like the scores."""
        key = tuple(sorted(picks))
        albums = np.array([m for m, _ in key], np.int64)
        return self._cached(self._support, key, lambda: (self.model.co_listeners(albums).astype(np.int32),
                                                          len(self.model.listeners(albums))))

    def match(self, seeds: dict[str, float], album_id: str) -> dict:
        """How well an album fits the taste in `seeds` (ADR 0019, revised for item kNN): its score's
        percentile, 0-100, among the albums at least MATCH_SHARE of the listeners who have one of the
        user's albums also have. The album itself is scored when it has the support `_need` asks of an album
        its size, so every For You pick gets a score (run 9). The album itself is left out of the query, so an album the user rated is
        scored as if they hadn't. status: ok | few_listeners (fewer of those listeners have it) |
        not_in_data (no model album) | no_taste (no seeds)."""
        album_id = self.catalog.canonical([album_id])[0]
        models = self.models_of.get(album_id)
        if not models:
            return {"status": "not_in_data"}
        weight, picks = self._seeds({a: w for a, w in seeds.items() if self.catalog.canonical([a])[0] != album_id})
        if not picks:
            return {"status": "no_taste"}
        scores = self.scores(picks)
        support, holders = self._support_of(picks)
        need = max(MATCH_MIN_SUPPORT, MATCH_SHARE * holders)
        out = {"listeners": holders, "with_album": int(support[models].max())}
        ref = self._cached(self._scores, ("ref", tuple(sorted(picks))), lambda: match_score.reference(
            scores, support, np.array([m for m, _ in picks], np.int64), eligible=self.shown, min_support=need))
        supported = (support[models] >= self._need(holders, self.model.popularity[models])).any()
        if not supported or len(ref) == 0:
            return {"status": "few_listeners", **out}
        return {"status": "ok", "score": round(match_score.percentile(ref, float(scores[models].max()))),
                "alongside": [a for _, a in self._contributions(weight, album_id)][:2], **out}

    def listeners_of(self, album_ids: list[str]) -> np.ndarray:
        """Historical listener indexes (never shown) holding any edition of these albums, for overlap counts."""
        models = self._model_ids(self.catalog.canonical(album_ids))
        if not models:
            return np.empty(0, np.int64)
        return self.model.listeners(np.array(models, np.int64))

    def similar(self, album_id: str, n: int = 12) -> list[str]:
        """The albums most similar to this one: the same listeners rank them highly."""
        return self.recommend([album_id], n=n)

    def related_artists(self, artist_id: str, n: int = 8) -> list[tuple[str, str]]:
        """(artist id, that artist's best-matching album id) for artists whose listeners overlap.
        The artist's top albums are the query; one album per artist, the artist's own albums excluded."""
        studio, other = self.catalog.artist_albums(artist_id)
        own = [a.id for a in studio + other]
        ids = self.recommend(own[:ARTIST_SEEDS], exclude=set(own), n=n * 3, artist_cap=1)
        return [(self.artist_of[i], i) for i in ids if self.artist_of.get(i) not in (None, artist_id)][:n]


@lru_cache
def get_engine() -> Engine:
    return Engine(model_dir(), get_catalog())
