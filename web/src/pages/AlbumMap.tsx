import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AlbumMapCanvas, stars, type MapHandle, type MapView } from "../components/AlbumMapCanvas";
import { Cover } from "../components/Cover";
import { ErrorNote } from "../components/Notice";
import { useFetch } from "../hooks/useFetch";
import { recall, remember } from "../hooks/useScrollMemory";
import { albumAt, buildModel, findOnMap, type MapModel } from "../lib/albumMap";
import { count } from "../lib/filters";
import { titleCase } from "../lib/text";
import { useLibrary } from "../state/library";

/** The Album Map (ADR 0022): the most-listened albums laid out by who listens to them, with your
 *  ratings and For You picks marked. ?album= selects one (album pages link here), ?genre= highlights one. */
export default function AlbumMap() {
  const map = useFetch(() => api.albumMap(), []);
  const model = useMemo(() => (map.data ? buildModel(map.data) : null), [map.data]);
  const { rated, loaded, ratingOf } = useLibrary();
  const mine = useFetch(() => api.myMap(), [rated.length], loaded);
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const handle = useRef<MapHandle>(null);
  const [showRated, setShowRated] = useState(true);
  const [showPicks, setShowPicks] = useState(true);

  const genre = params.get("genre");
  const asked = params.get("album");
  const selected = model && asked ? model.indexOf.get(asked) ?? null : null;
  const missing = model && asked && selected === null ? asked : null;

  const ratedOnMap = useMemo(() => {
    const out = new Map<number, number>();
    if (model) for (const r of rated) { const i = model.indexOf.get(r.album.id); if (i !== undefined) out.set(i, r.rating); }
    return out;
  }, [model, rated]);
  const picksOnMap = useMemo(() => {
    const out = new Map<number, number>();
    if (model && mine.data) mine.data.recommended.forEach((id, rank) => { const i = model.indexOf.get(id); if (i !== undefined) out.set(i, rank); });
    return out;
  }, [model, mine.data]);
  const highlight = useMemo(() => {
    const g = model && genre ? model.genres.find((x) => x.name === genre) : null;
    return g ? new Set(g.albums) : null;
  }, [model, genre]);

  const setParam = (key: string, value: string | null) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (value) next.set(key, value); else next.delete(key);
    return next;
  }, { replace: true });
  const select = (i: number | null) => setParam("album", i === null || !model ? null : model.ids[i]);

  // The view is remembered per history entry, so Back from an album page lands where you were.
  const entry = useRef(location.key);
  entry.current = location.key;
  const [initialView] = useState(() => recall<MapView>(location.key, "map"));
  const saveView = useMemo(() => {
    let t = 0;
    return (v: MapView) => { clearTimeout(t); t = window.setTimeout(() => remember(entry.current, "map", v), 150); };
  }, []);

  // Arriving with ?album= (from an album page): fly there once the map has loaded.
  const flown = useRef(false);
  useEffect(() => {
    if (!model || flown.current) return;
    flown.current = true;
    if (selected !== null && !initialView) requestAnimationFrame(() => handle.current?.flyTo(selected));
  }, [model, selected, initialView]);

  if (map.error) {
    return (
      <section className="section">
        <h1 className="page-title">Album Map</h1>
        <ErrorNote error={map.error} />
      </section>
    );
  }

  const nRated = rated.length;
  return (
    <section className="section map-page">
      <h1 className="page-title">Album Map</h1>
      <p className="muted map-intro">
        {model ? `The ${count(model.n)} most-listened albums` : "The most-listened albums"} in the listening data, placed by who listens to them.
        Albums sit close together when the same people love them, so genres, scenes and countries form neighbourhoods. Zoom in to see the covers.
      </p>

      <div className="toolbar map-toolbar">
        {model && <MapFind model={model} onPick={(i) => { select(i); handle.current?.flyTo(i); }} />}
        <label className="sort map-genre">
          <span className="visually-hidden">Highlight a genre</span>
          <select value={genre ?? ""} onChange={(e) => setParam("genre", e.target.value || null)} disabled={!model}>
            <option value="">Highlight a Genre</option>
            {model?.genres.slice().sort((a, b) => a.name.localeCompare(b.name)).map((g) => (
              <option key={g.name} value={g.name}>{titleCase(g.name)} ({count(g.albums.length)})</option>
            ))}
          </select>
        </label>
        <div className="map-toggles">
          <button type="button" className={showRated ? "filter active" : "filter"} aria-pressed={showRated}
            onClick={() => setShowRated((v) => !v)} disabled={!ratedOnMap.size}>Your Ratings</button>
          <button type="button" className={showPicks ? "filter active" : "filter"} aria-pressed={showPicks}
            onClick={() => setShowPicks((v) => !v)} disabled={!picksOnMap.size}>For You</button>
          <button type="button" className="btn btn-quiet btn-small" disabled={!ratedOnMap.size && !picksOnMap.size}
            onClick={() => handle.current?.fit([...(showRated ? ratedOnMap.keys() : []), ...(showPicks ? picksOnMap.keys() : [])])}>
            Zoom to Yours
          </button>
        </div>
      </div>

      <div className="map-frame">
        {model ? (
          <AlbumMapCanvas ref={handle} model={model} rated={ratedOnMap} picks={picksOnMap} highlight={highlight}
            showRated={showRated} showPicks={showPicks} selected={selected} onSelect={select}
            initialView={initialView} onViewChange={saveView}
            label={`Map of ${count(model.n)} albums. Use Find on the Map to reach an album, or arrow keys and plus and minus to move and zoom.`} />
        ) : (
          <div className="map-loading skel" role="status"><span className="visually-hidden">Loading the map</span></div>
        )}
        {model && (
          <div className="map-zoom">
            <button type="button" className="map-zoom-btn" onClick={() => handle.current?.zoomBy(1.8)} aria-label="Zoom in">+</button>
            <button type="button" className="map-zoom-btn" onClick={() => handle.current?.zoomBy(1 / 1.8)} aria-label="Zoom out">−</button>
            <button type="button" className="map-zoom-btn map-zoom-fit" onClick={() => handle.current?.reset()}>Fit</button>
          </div>
        )}
        {model && selected !== null && (
          <SelectedCard model={model} i={selected} rating={ratingOf(model.ids[selected])}
            pick={picksOnMap.get(selected) ?? null} onClose={() => select(null)} />
        )}
      </div>
      <p className="visually-hidden" aria-live="polite">{model && selected !== null ? `Selected ${model.titles[selected]} by ${model.artists[selected]}` : ""}</p>

      {missing && (
        <p className="nudge">That album isn't on the map. The map holds the {model ? count(model.n) : ""} most-listened albums in the listening data.</p>
      )}
      <ul className="map-legend" aria-label="Legend">
        <li><svg width="22" height="14" aria-hidden="true"><circle cx="5" cy="7" r="2" className="lg-dot" /><circle cx="15" cy="7" r="4" className="lg-dot" /></svg>Album, bigger with more listeners</li>
        {highlight && genre && <li><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4" className="lg-hl" /></svg>{titleCase(genre)} ({count(highlight.size)})</li>}
        <li className={showRated && ratedOnMap.size ? "" : "off"}>
          <svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" className="lg-rated" /></svg>
          Rated by You ({ratedOnMap.size ? `${count(ratedOnMap.size)} of ${count(nRated)} on the map` : nRated ? "none on the map" : "nothing rated yet"})
        </li>
        <li className={showPicks && picksOnMap.size ? "" : "off"}>
          <svg width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" className="lg-pick" /></svg>
          On Your For You ({picksOnMap.size ? `${count(picksOnMap.size)} on the map` : nRated ? "none on the map" : "rate albums to get picks"})
        </li>
      </ul>
      <p className="muted map-help">
        Drag to move. Scroll, pinch or use the + and − buttons to zoom, and double-click to zoom in on a spot. With the map focused,
        arrow keys move it, + and − zoom, 0 fits the whole map and Escape clears the selection.
        {nRated === 0 && <> <Link to="/start">Rate a few albums</Link> to see where your taste sits.</>}
      </p>
    </section>
  );
}

function SelectedCard({ model, i, rating, pick, onClose }: { model: MapModel; i: number; rating: number | null; pick: number | null; onClose: () => void }) {
  const album = albumAt(model, i);
  return (
    <div className="map-card" role="region" aria-label="Selected album">
      <Link to={`/album/${album.id}`} className="map-card-art" tabIndex={-1} aria-hidden="true"><Cover album={album} /></Link>
      <div className="map-card-copy">
        <Link to={`/album/${album.id}`} className="map-card-title">{album.title}</Link>
        <span className="map-card-artist">{album.artist}</span>
        <span className="map-card-meta">{album.year ? `${album.year}, ` : ""}{count(model.listeners[i])} listeners in the data</span>
        {rating !== null && <span className="map-card-mark rated">You rated it {stars(rating)}</span>}
        {rating === null && pick !== null && <span className="map-card-mark pick">Number {pick + 1} on your For You</span>}
        <div className="map-card-actions">
          <Link to={`/album/${album.id}`} className="btn btn-small">Open Album</Link>
          <button type="button" className="btn btn-quiet btn-small" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

/** "Find on the Map": searches the map's own albums as you type, arrow keys and Enter to pick one. */
function MapFind({ model, onPick }: { model: MapModel; onPick: (i: number) => void }) {
  const id = useId();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const hits = useMemo(() => findOnMap(model, q), [model, q]);
  const showing = open && q.trim().length > 0;
  const choose = (i: number) => { onPick(i); setQ(""); setOpen(false); };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!hits.length) return;
      e.preventDefault();
      setOpen(true);
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (hits[active] !== undefined) choose(hits[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };
  return (
    <div className="map-find">
      <input type="search" value={q} placeholder="Find on the Map" aria-label="Find an album on the map"
        role="combobox" aria-autocomplete="list" aria-expanded={showing} aria-controls={`${id}-list`}
        aria-activedescendant={showing && hits.length ? `${id}-${active}` : undefined}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={keys} />
      {showing && (
        <ul className="suggest" id={`${id}-list`} role="listbox" aria-label="Albums on the map">
          {hits.length === 0 && <li className="suggest-empty">No album on the map matches</li>}
          {hits.map((i, k) => (
            <li key={i} id={`${id}-${k}`} role="option" aria-selected={k === active}
              className={k === active ? "suggest-option active" : "suggest-option"}
              onPointerDown={(e) => e.preventDefault()} onClick={() => choose(i)} onMouseMove={() => setActive(k)}>
              <span className="suggest-art" aria-hidden="true"><Cover album={albumAt(model, i)} /></span>
              <span className="suggest-text"><span className="suggest-name">{model.titles[i]}</span><span className="suggest-sub">{model.artists[i]}</span></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
