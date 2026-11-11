import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Album } from "../types";
import { useFetch } from "../hooks/useFetch";
import { AlbumGrid } from "../components/AlbumCard";
import { ErrorNote, SkeletonGrid } from "../components/Notice";
import { Pager } from "../components/Pager";
import { formatStars } from "../components/Stars";
import { ActiveFilters, FilterModal } from "../components/FilterModal";
import { count, forYouFilters, readFilters, toQuery, writeFilters, type FilterKey, type Filters } from "../lib/filters";
import { useLibrary } from "../state/library";

const MIN = 3;
const NOTE_MS = 6000;   // how long "Updated for your rating" stays
const UNDO_MS = 6000;
const PAGE_SIZE = 24;
const DEPTH_KEY = "inrotation.depth";
// The API's listener caps (backend/app/engine.py LISTENER_CAPS), out of about 476,000 listeners.
const DEPTHS = [
  { label: "Anything", hint: "Your best matches, however popular they are." },
  { label: "Less Known", hint: "Albums with fewer than 5,000 listeners." },
  { label: "Under the Radar", hint: "Albums with fewer than 1,000 listeners." },
  { label: "Deep Cuts", hint: "Albums with fewer than 200 listeners." },
];

function storedDepth(): number {
  try {
    const n = Number(localStorage.getItem(DEPTH_KEY));
    return Number.isInteger(n) && n >= 0 && n < DEPTHS.length ? n : 0;
  } catch {
    return 0;
  }
}

/** Steps sit at fixed positions (--i of --last), shared by the dots and the labels so they always line up
 *  with the thumb. Styles: .depth in styles.css. */
function DepthSlider({ value, onChange }: { value: number; onChange: (depth: number) => void }) {
  const last = DEPTHS.length - 1;
  const at = (i: number) => ({ "--i": i } as React.CSSProperties);
  return (
    <div className="depth" style={{ "--last": last } as React.CSSProperties}>
      <label htmlFor="depth" className="depth-title">How Well Known?</label>
      <div className="depth-scale">
        <div className="depth-rail">
          {DEPTHS.map((d, i) => <span key={d.label} className={i <= value ? "depth-dot on" : "depth-dot"} style={at(i)} aria-hidden="true" />)}
          <input id="depth" type="range" min={0} max={last} step={1} value={value}
            aria-valuetext={DEPTHS[value].label} onChange={(e) => onChange(Number(e.target.value))} />
        </div>
        <div className="depth-stops" aria-hidden="true">
          {DEPTHS.map((d, i) => (
            <button key={d.label} type="button" tabIndex={-1} className={i === value ? "active" : ""} style={at(i)} onClick={() => onChange(i)}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
      <p className="depth-hint">{DEPTHS[value].hint}</p>
    </div>
  );
}

export default function ForYou() {
  const { queryCount, rated, loaded, whenSynced, setDismissed } = useLibrary();
  const enough = queryCount >= MIN;
  // Bumped after a dismissal is saved, so the list refills from the server.
  const [version, setVersion] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [undo, setUndo] = useState<Album | null>(null);
  const [depth, setDepth] = useState(storedDepth);
  // The page lives in the URL (?page=2), so Back and shared links keep it.
  const [params, setParams] = useSearchParams();
  const asked = Number(params.get("page"));
  const page = Number.isInteger(asked) && asked >= 1 ? asked : 1;
  // Genre, decade, album length and type, in the URL like Browse Albums' filters (ADR 0026).
  const filters = forYouFilters(readFilters(params));
  const filterKey = JSON.stringify(filters);
  // Diversify (ADR 0029): each pick is also chosen for being unlike the ones above it. In the URL (?diverse=1).
  const diverse = params.get("diverse") === "1";
  const active = Object.keys(filters).length;
  const [modal, setModal] = useState(false);
  const options = useFetch(api.browseOptions, [], active > 0);   // chip labels
  const top = useRef<HTMLDivElement>(null);
  const recs = useFetch(
    async () => {
      await whenSynced();
      return api.recommendations(depth, (page - 1) * PAGE_SIZE, PAGE_SIZE, toQuery(filters), diverse);
    },
    [queryCount, rated, version, depth, page, filterKey, diverse],
    enough,
  );
  const pages = recs.data ? Math.ceil(recs.data.total / PAGE_SIZE) : 0;

  // A rating changed while you're here (the badge on a card): once the refreshed list arrives, say so.
  const before = useRef<{ loaded: boolean; ratings: Map<string, number> }>({ loaded, ratings: new Map() });
  // The text, and the response on screen when it changed: the note waits for a newer one.
  const [changed, setChanged] = useState<{ text: string; shown: unknown } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    const was = before.current;
    const now = new Map(rated.map((r) => [r.album.id, r.rating]));
    before.current = { loaded, ratings: now };
    if (!was.loaded) return;   // the library arriving isn't a change you made
    const ids = new Set([...was.ratings.keys(), ...now.keys()]);
    const diff = [...ids].filter((id) => was.ratings.get(id) !== now.get(id));
    if (diff.length !== 1) return;
    const id = diff[0], stars = now.get(id);
    const title = rated.find((r) => r.album.id === id)?.album.title ?? recs.data?.items.find((a) => a.id === id)?.title;
    if (!title) return;
    setChanged({ shown: recs.data, text: stars === undefined ? `Updated after you cleared your rating of ${title}.` : `Updated for your ${formatStars(stars)}-star rating of ${title}.` });
  }, [rated, loaded]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (changed && recs.data && recs.data !== changed.shown && !recs.loading) {
      setNote(changed.text);
      setChanged(null);
    }
  }, [changed, recs.data, recs.loading]);
  useEffect(() => {
    if (!note) return;
    const t = setTimeout(() => setNote(null), NOTE_MS);
    return () => clearTimeout(t);
  }, [note]);

  const goTo = (n: number, scroll = true) => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (n <= 1) next.delete("page"); else next.set("page", String(n));
      return next;
    }, { replace: !scroll });
    if (scroll) top.current?.scrollIntoView({ block: "start" });
  };

  // Past the end (after dismissals, or a stale link): go to the last page there is.
  useEffect(() => {
    if (recs.data && !recs.loading && pages > 0 && page > pages) goTo(pages, false);
  });

  useEffect(() => {
    if (!undo) return;
    const t = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(t);
  }, [undo]);

  const changeDepth = (d: number) => {
    setDepth(d);
    if (page !== 1) goTo(1, false);
    try {
      localStorage.setItem(DEPTH_KEY, String(d));
    } catch {
      // Private windows can block storage; the setting then lasts for this visit only.
    }
  };

  const toggleDiverse = () => {
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (diverse) next.delete("diverse"); else next.set("diverse", "1");
      next.delete("page");
      return next;
    });
  };

  // New filters start again at page 1.
  const applyFilters = (next: Filters) => {
    setParams((p) => {
      const out = writeFilters(p, forYouFilters(next));
      out.delete("page");
      return out;
    });
    setModal(false);
  };
  const removeFilter = (k: FilterKey) => applyFilters({ ...filters, [k]: undefined });

  const toggle = (album: Album, on: boolean) => {
    setHidden((h) => {
      const next = new Set(h);
      if (on) next.add(album.id); else next.delete(album.id);
      return next;
    });
    setUndo(on ? album : null);
    setDismissed(album, on).then(() => setVersion((v) => v + 1), () => undefined);   // failures show the banner
  };

  const items = recs.data?.items.filter((a) => !hidden.has(a.id)) ?? [];
  // "Because you rated X and Y": the rated albums that carry the most of its score, the ones it stands out as close to first.
  const titles = new Map(rated.map((r) => [r.album.id, r.album.title]));
  const because = (a: Album) => {
    const names = (recs.data?.because?.[a.id] ?? []).map((id) => titles.get(id)).filter((t): t is string => !!t);
    return names.length ? `Because you rated ${names.join(" and ")}` : null;
  };
  return (
    <section className="section">
      <h1 className="page-title">For You</h1>
      {!enough ? (
        <p className="muted">Rate at least {MIN} albums 3 stars or more to get suggestions. <Link to="/start">Rate some albums</Link>.</p>
      ) : (
        <>
          <p className="muted">
            {recs.data?.source === "popularity"
              ? "We couldn't match your ratings to listening data yet, so these are the most-listened albums."
              : `Based on the ${queryCount} albums you rated 3 stars or more, weighted by your stars, and the albums the same listeners rank alongside them.`}
            {" "}Tap the X on an album you don't want suggested. <Link to="/how-recommendations-work">How Recommendations Work</Link>
          </p>
          <DepthSlider value={depth} onChange={changeDepth} />
          <div className="toolbar for-you-toolbar">
            <div className="toolbar-status">
              <p className="toolbar-count" role="status">
                {recs.data ? `${count(recs.data.total)} ${recs.data.total === 1 ? "Pick" : "Picks"}` : "Loading..."}
              </p>
              {active > 0 && <ActiveFilters filters={filters} options={options.data} onRemove={removeFilter} />}
              {active > 1 && <button type="button" className="link-button toolbar-clear" onClick={() => applyFilters({})}>Clear All</button>}
            </div>
            <div className="toolbar-actions">
              <button type="button" className="btn btn-quiet btn-small btn-toggle" aria-pressed={diverse} onClick={toggleDiverse}>
                Diversify
              </button>
              <button type="button" className="btn btn-quiet btn-small" aria-haspopup="dialog" onClick={() => setModal(true)}>
                {active ? `Filters (${active})` : "Filters"}
              </button>
            </div>
          </div>
          {diverse && <p className="muted diverse-note">Diversified: each pick is also chosen for being unlike the ones above it, so more corners of your taste show up.</p>}
          {recs.error && <ErrorNote error={recs.error} />}
          {!recs.data && recs.loading && <SkeletonGrid count={PAGE_SIZE} label="Finding albums" />}
          <div ref={top} className="for-you-top" />
          {recs.data && (
            <div className={recs.loading ? "refreshing" : undefined} aria-busy={recs.loading}>
              {items.length === 0 && recs.data.total === 0
                ? <p className="muted">{active
                  ? `Nothing close to your taste matches ${active > 1 ? "these filters" : "this filter"}${depth > 0 ? " at this setting" : ""}. Try removing a filter${depth > 0 ? " or moving the slider toward Anything" : ""}.`
                  : `Nothing new to suggest yet. Try rating a few more albums${depth > 0 ? " or move the slider toward Anything" : ""}.`}</p>
                : (
                  <>
                    {note && <p className="update-note" role="status">{note}</p>}
                    {pages > 1 && <p className="toolbar-count pager-status">Page {page} of {pages}</p>}
                    <AlbumGrid albums={items} onDismiss={(a) => toggle(a, true)} detail={because} />
                    <Pager page={Math.min(page, pages)} pages={pages} onPage={goTo} label="For You pages" />
                  </>
                )}
            </div>
          )}
        </>
      )}
      {undo && (
        <div className="toast" role="status">
          <span>Removed <strong>{undo.title}</strong> from For you.</span>
          <button className="btn" onClick={() => toggle(undo, false)}>Undo</button>
        </div>
      )}
      <FilterModal forYou open={modal} filters={filters} onApply={applyFilters} onClose={() => setModal(false)} />
    </section>
  );
}
