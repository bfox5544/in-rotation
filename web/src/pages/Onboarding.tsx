import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useFetch } from "../hooks/useFetch";
import { Cover } from "../components/Cover";
import { Stars } from "../components/Stars";
import { SearchBox, type SearchOption } from "../components/SearchBox";
import type { Album } from "../types";
import { ErrorNote, SkeletonGrid } from "../components/Notice";
import { useLibrary } from "../state/library";

const NEEDED = 5;

type View = { kind: "popular" } | { kind: "search"; q: string } | { kind: "artist"; id: string; name: string } | { kind: "album"; album: Album; q: string };

export default function Onboarding() {
  const { queryCount, rated } = useLibrary();
  // What the grid shows: popular albums, a search, one artist's albums, or a chosen album first among its title's matches.
  const [view, setView] = useState<View>({ kind: "popular" });
  const albums = useFetch(() => view.kind === "artist" ? api.albums({ artist: view.id, sort: "popular" })
    : api.albums({ q: view.kind === "popular" ? undefined : view.q }), [view]);
  const items = view.kind === "album" && albums.data
    ? [view.album, ...albums.data.items.filter((a) => a.id !== view.album.id)]
    : albums.data?.items;
  const pick = (o: SearchOption, term: string) => setView(
    o.kind === "artist" ? { kind: "artist", id: o.artist.id, name: o.artist.name }
      : o.kind === "album" ? { kind: "album", album: o.album, q: o.album.title }
      : { kind: "search", q: term });
  const nav = useNavigate();
  const ready = queryCount >= NEEDED;
  return (
    <section className="section">
      <h1 className="page-title">Rate Albums You Know</h1>
      <p className="muted">
        Rate at least {NEEDED} albums you like (3 stars or more). Half stars count. Low ratings help too: those albums
        won't be suggested. The more you rate, the better the suggestions.
      </p>
      <SearchBox className="search pick-search" placeholder="Find an album or artist" onPick={pick}
        onClear={() => setView({ kind: "popular" })} />
      {view.kind === "artist" && <p className="muted pick-showing">Albums by {view.name}</p>}
      {view.kind === "search" && albums.data?.items.length === 0 && <p className="muted">No albums match "{view.q}".</p>}
      {albums.error && <ErrorNote error={albums.error} />}
      {!albums.data && albums.loading && <SkeletonGrid count={18} />}
      <div className="grid">
        {items?.map((a) => (
          <article key={a.id} className="card rate-card">
            <Link to={`/album/${a.id}`} aria-label={`${a.title} by ${a.artist}`}><Cover album={a} /></Link>
            <span className="card-title">{a.title}</span>
            <span className="card-artist">{a.artist}</span>
            <Stars album={a} size={22} compact />
          </article>
        ))}
      </div>
      <div className="pickbar">
        <span>{ready ? `${rated.length} rated` : `${queryCount} of ${NEEDED} liked albums rated`}</span>
        <button className="btn" disabled={!ready} onClick={() => nav("/for-you")}>See Suggestions</button>
      </div>
    </section>
  );
}
