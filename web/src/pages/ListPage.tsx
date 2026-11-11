import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Album } from "../types";
import { AlbumGrid } from "../components/AlbumCard";
import { Cover } from "../components/Cover";
import { ListArt } from "../components/ListTile";
import { SkeletonGrid } from "../components/Notice";
import { Stars, formatStars } from "../components/Stars";
import { since, waiting, WAIT_DAYS } from "../lib/listenLater";
import { useLibrary } from "../state/library";
import { useToast } from "../state/toast";

const SORTS = { added: "Date Added", artist: "Artist", year: "Release Year", rating: "Your Rating" } as const;
type Sort = keyof typeof SORTS;

/** One of your lists on its own page: /library/lists/:id, or /library/listen-later. Lists are private. */
export default function ListPage() {
  const { id } = useParams();
  const { lists, later, laterAdded, loaded, error, ratingOf, renameList, deleteList, restoreList } = useLibrary();
  const nav = useNavigate();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  // The sort lives in the URL (?sort=artist), so Back and shared links keep it.
  const [params, setParams] = useSearchParams();
  const asked = params.get("sort");
  const sort: Sort = asked && asked in SORTS ? (asked as Sort) : "added";

  const isLater = id === undefined;
  const list = isLater ? null : lists.find((l) => String(l.id) === id);
  if (!loaded && !error) {
    return (
      <section className="section">
        <BackLink />
        <SkeletonGrid count={6} label="Loading the list" />
      </section>
    );
  }
  if (!isLater && !list) {
    return (
      <section className="section">
        <BackLink />
        <h1 className="page-title">List Not Found</h1>
        <p className="muted">This list doesn't exist or was deleted.</p>
      </section>
    );
  }
  const title = list ? list.name : "Listen Later";
  const albums = list ? list.albums : later;
  const added = (list ? list.added : laterAdded) ?? {};
  const n = albums.length;

  const save = (e: FormEvent) => {
    e.preventDefault();
    if (list && name.trim() && name.trim() !== list.name) renameList(list.id, name.trim());
    setEditing(false);
  };
  // Delete straight away, with Undo, rather than a confirm box.
  const remove = () => {
    if (!list) return;
    const { name: was, albums: had } = list;
    deleteList(list.id);
    nav("/library", { replace: true });
    toast({
      message: <>Deleted <strong>{was}</strong>.</>,
      action: { label: "Undo", run: () => void restoreList(was, had).catch(() => undefined) },
    });
  };
  const setSort = (s: Sort) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (s === "added") next.delete("sort"); else next.set("sort", s);
    return next;
  }, { replace: true });

  return (
    <section className="section">
      <BackLink />
      <header className="list-page-head">
        <ListArt albums={albums} />
        <div className="list-page-copy">
          {editing ? (
            <form onSubmit={save} className="list-new">
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoFocus aria-label="List name" />
              <button className="btn" type="submit">Save</button>
            </form>
          ) : (
            <h1 className="page-title">{title}</h1>
          )}
          <p className="muted">{n === 0 ? "No albums yet" : `${n.toLocaleString("en")} ${n === 1 ? "Album" : "Albums"}`}</p>
          {list && !editing && (
            <div className="list-page-actions">
              <button type="button" className="btn btn-quiet btn-small" onClick={() => { setName(list.name); setEditing(true); }}>Rename</button>
              <button type="button" className="btn btn-quiet btn-small" onClick={remove}>Delete</button>
            </div>
          )}
        </div>
      </header>
      {isLater && <ListenedYet />}
      {n === 0 ? (
        <p className="muted">
          {isLater ? "Nothing saved. Tap the bookmark on an album to add it here." : "Empty. Tap the bookmark on any album to add it here."}
        </p>
      ) : (
        <>
          {n > 1 && (
            <div className="toolbar list-toolbar">
              <p className="toolbar-count">{sort === "added" ? "Newest first" : `By ${SORTS[sort].toLowerCase()}`}</p>
              <label className="sort">
                <span className="visually-hidden">Sort by</span>
                <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                  {(Object.keys(SORTS) as Sort[]).map((k) => <option key={k} value={k}>{SORTS[k]}</option>)}
                </select>
              </label>
            </div>
          )}
          <AlbumGrid albums={sorted(albums, sort, ratingOf)}
            detail={sort === "added" ? (a) => added[a.id] && `Added ${since(added[a.id])}` : sort === "year" ? (a) => (a.year ? String(a.year) : null)
              : sort === "rating" ? (a) => { const r = ratingOf(a.id); return r === null ? "Not rated" : `★ ${formatStars(r)}`; } : undefined} />
        </>
      )}
    </section>
  );
}

/** Newest first as stored, or by artist (A to Z), release year (newest first) or your rating (highest first).
 *  Albums missing a year or a rating go last; ties keep the newest-added order. */
function sorted(albums: Album[], sort: Sort, ratingOf: (id: string) => number | null): Album[] {
  const key: Record<Sort, ((a: Album, b: Album) => number) | null> = {
    added: null,
    artist: (a, b) => a.artist.localeCompare(b.artist, "en", { sensitivity: "base" }) || (a.year ?? 9999) - (b.year ?? 9999),
    year: (a, b) => (b.year ?? -1) - (a.year ?? -1),
    rating: (a, b) => (ratingOf(b.id) ?? -1) - (ratingOf(a.id) ?? -1),
  };
  const by = key[sort];
  return by ? [...albums].sort(by) : albums;
}

/** Albums that have waited in Listen Later for a week or more without a rating. Rating one here keeps it
 *  on screen with a Remove button, since having listened usually means it can leave the list. */
function ListenedYet() {
  const { later, laterAdded, ratingOf, toggleLater } = useLibrary();
  // Taken once, so an album stays in the prompt after you rate it here.
  const [ids, setIds] = useState<string[] | null>(null);
  useEffect(() => {
    if (ids === null) setIds(waiting(later, laterAdded, ratingOf).map((a) => a.id));
  }, [ids, later, laterAdded, ratingOf]);
  const rows = (ids ?? []).map((i) => later.find((a) => a.id === i)).filter((a): a is Album => !!a);
  if (!rows.length) return null;
  return (
    <section className="listened" aria-labelledby="listened-heading">
      <h2 id="listened-heading">Listened Yet?</h2>
      <p className="muted">
        {rows.length === 1 ? "This album has" : `These ${rows.length} albums have`} waited here for over {WAIT_DAYS === 7 ? "a week" : `${WAIT_DAYS} days`}.
        {" "}Rate the ones you've heard and they'll shape your recommendations.
      </p>
      <ul className="listened-list">
        {rows.map((a) => {
          const rated = ratingOf(a.id) !== null;
          return (
            <li key={a.id}>
              <Link to={`/album/${a.id}`} className="listened-art" aria-label={`${a.title} by ${a.artist}`}><Cover album={a} /></Link>
              <div className="listened-copy">
                <Link to={`/album/${a.id}`} className="listened-title">{a.title}</Link>
                <span className="listened-artist">{a.artist}</span>
                <span className="listened-when">Saved {since(laterAdded[a.id])}</span>
              </div>
              <div className="listened-actions">
                <Stars album={a} size={20} compact />
                {rated && <button type="button" className="btn btn-quiet btn-small" onClick={() => toggleLater(a)}>Remove from Listen Later</button>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function BackLink() {
  return <Link to="/library" className="back-link">← Library</Link>;
}
