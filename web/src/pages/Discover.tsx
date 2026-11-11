import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Album } from "../types";
import { useFetch } from "../hooks/useFetch";
import { AlbumGrid } from "../components/AlbumCard";
import { Cover } from "../components/Cover";
import { ActiveFilters, FilterModal } from "../components/FilterModal";
import { ErrorNote, SkeletonGrid } from "../components/Notice";
import { activeCount, cardDetail, count, readFilters, SORT_LABELS, toQuery, writeFilters,
         type FilterKey, type Filters } from "../lib/filters";
import { useLibrary } from "../state/library";
import { recall, remember } from "../hooks/useScrollMemory";

const PAGE = 48;
const MAX_RESTORED = PAGE * 10;   // albums reloaded on Back at most
const COLLAGE = 7;      // covers in the hero collage; their sizes and offsets are in styles.css (.collage)
const PICKS = 6;        // recommendations shown instead of the hero
const PICKS_AFTER = 5;  // ratings before Picked for You appears under the hero

function Hero() {
  const covers = useFetch(() => api.albums({ limit: COLLAGE }), []);
  return (
    <section className="hero">
      <div className="hero-copy">
        <h1>Tired of listening to the same music?</h1>
        <p>Choose a few albums you love. We'll find the albums their listeners love too and help you discover what to hear next.</p>
        <Link to="/start" className="btn">Choose Your Albums</Link>
      </div>
      <div className="collage" aria-hidden="true">
        {covers.data?.items.map((a, i) => <div key={a.id} className={`collage-${i + 1}`}><Cover album={a} /></div>)}
      </div>
    </section>
  );
}

/** Before Picked for You unlocks: how many ratings so far, and how many to go. */
function PicksProgress({ have }: { have: number }) {
  const left = PICKS_AFTER - have;
  return (
    <section className="picks-progress" aria-labelledby="progress-heading">
      <div className="progress-copy">
        <h2 id="progress-heading">{have} of {PICKS_AFTER} Rated</h2>
        <p className="muted">Rate {left} more {left === 1 ? "album" : "albums"} to see the albums closest to your taste.</p>
      </div>
      <div className="progress-steps" role="progressbar" aria-valuemin={0} aria-valuemax={PICKS_AFTER} aria-valuenow={have}
        aria-label="Ratings toward Picked for You">
        {Array.from({ length: PICKS_AFTER }, (_, i) => <span key={i} className={i < have ? "done" : undefined} />)}
      </div>
      <Link to="/start" className="btn">Keep Rating</Link>
    </section>
  );
}

/** Once someone has rated enough albums, their best recommendations appear under the hero. */
function Picks() {
  const { rated, whenSynced } = useLibrary();
  const recs = useFetch(async () => {
    await whenSynced();
    return api.recommendations(0);
  }, [rated.length]);
  const items = recs.data?.items.slice(0, PICKS) ?? [];
  return (
    <section className="picks" aria-labelledby="picks-heading">
      <div className="section-head">
        <h2 id="picks-heading">Picked for You</h2>
        <Link to="/for-you" className="link-button">See All Recommendations</Link>
      </div>
      <p className="muted">
        {recs.data?.source === "popularity"
          ? "We couldn't match your ratings to listening data yet, so these are the most-listened albums."
          : `From the ${rated.length} albums you've rated and the listeners who share your taste.`}
      </p>
      {recs.error && <ErrorNote error={recs.error} />}
      {!recs.data && recs.loading && <div className="picks-row"><SkeletonGrid count={PICKS} label="Finding albums" /></div>}
      {items.length > 0 && <div className="picks-row"><AlbumGrid albums={items} /></div>}
    </section>
  );
}

export default function Discover() {
  const { rated, loaded } = useLibrary();
  // Filters live in the URL (shareable, Back works) and are edited in the modal (ADR 0015).
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const key = JSON.stringify(filters);
  const [modal, setModal] = useState(false);
  const active = activeCount(filters);
  const options = useFetch(api.browseOptions, [], active > 0);   // chip labels

  // Results: the first page loads with the filters; "Show more" appends pages.
  const [pages, setPages] = useState<{ key: string; items: Album[]; total: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const requestId = useRef(0);
  const { key: entry } = useLocation();
  // `count` albums from `offset`, in pages of PAGE. Back restores as many as were shown (useScrollMemory).
  const load = (offset: number, count = PAGE) => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    const starts = Array.from({ length: Math.ceil(count / PAGE) }, (_, i) => offset + i * PAGE);
    Promise.all(starts.map((o) => api.albums({ ...toQuery(filters), limit: PAGE, offset: o }))).then(
      (got) => {
        if (id !== requestId.current) return;
        const fresh = got.flatMap((p) => p.items);
        setPages((prev) => {
          const items = offset && prev?.key === key ? [...prev.items, ...fresh] : fresh;
          remember(entry, "browse", { key, shown: items.length });
          return { key, total: got[0].total, items };
        });
        setLoading(false);
      },
      (e: Error) => {
        if (id !== requestId.current) return;
        setError(e);
        setLoading(false);
      },
    );
  };
  useEffect(() => {
    const before = recall<{ key: string; shown: number }>(entry, "browse");
    load(0, before?.key === key ? Math.min(Math.max(before.shown, PAGE), MAX_RESTORED) : PAGE);
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (next: Filters) => {
    setParams(writeFilters(params, next));
    setModal(false);
  };
  const remove = (k: FilterKey) => apply({ ...filters, [k]: undefined });

  const items = pages?.key === key ? pages.items : [];
  const total = pages?.key === key ? pages.total : null;
  const sort = filters.sort ?? "popular";
  const albums = (n: number) => `${count(n)} ${n === 1 ? "Album" : "Albums"}`;

  return (
    <>
      <Hero />
      {rated.length >= PICKS_AFTER ? <Picks /> : loaded && rated.length > 0 && <PicksProgress have={rated.length} />}
      <section className="section browse" aria-labelledby="browse-heading">
        <h2 id="browse-heading">Browse Albums</h2>
        <div className="toolbar">
          <div className="toolbar-status">
            <p className="toolbar-count" role="status">{total === null ? "Loading..." : albums(total)}</p>
            {active > 0 && <ActiveFilters filters={filters} options={options.data} onRemove={remove} />}
            {active > 1 && <button type="button" className="link-button toolbar-clear" onClick={() => apply({ sort: filters.sort })}>Clear All</button>}
          </div>
          <div className="toolbar-actions">
            <label className="sort">
              <span className="visually-hidden">Sort by</span>
              <select value={sort} onChange={(e) => apply({ ...filters, sort: e.target.value === "popular" ? undefined : e.target.value })}>
                {Object.entries(SORT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <button type="button" className="btn btn-quiet btn-small" aria-haspopup="dialog" onClick={() => setModal(true)}>
              {active ? `Filters (${active})` : "Filters"}
            </button>
          </div>
        </div>
        {sort === "rated" && (
          <p className="muted toolbar-note">Highest rated uses MusicBrainz community ratings. Ratings with few votes count for less, and unrated albums come last.</p>
        )}
        {error && <ErrorNote error={error} />}
        {total === 0 && !loading && <p className="muted">No albums match all of these. Try removing a filter.</p>}
        {!items.length && loading && <SkeletonGrid count={18} />}
        {items.length > 0 && <AlbumGrid albums={items} detail={active || sort !== "popular" ? cardDetail(sort) : undefined} />}
        {total !== null && items.length < total && (
          <div className="browse-more">
            <button type="button" className="btn btn-quiet" disabled={loading} onClick={() => load(items.length)}>
              {loading ? "Loading..." : `Show More (${count(total - items.length)} Left)`}
            </button>
          </div>
        )}
      </section>
      <FilterModal open={modal} filters={filters} onApply={apply} onClose={() => setModal(false)} />
    </>
  );
}
