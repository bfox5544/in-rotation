import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useFetch } from "../hooks/useFetch";
import { AlbumGrid } from "../components/AlbumCard";
import { ErrorNote, SkeletonGrid } from "../components/Notice";

export default function Search() {
  const [params] = useSearchParams();
  const q = (params.get("q") ?? "").trim();
  const results = useFetch(() => api.albums({ q }), [q], q.length > 0);
  const artists = useFetch(() => api.artists(q), [q], q.length > 0);
  const items = results.data?.items ?? [];
  return (
    <section className="section">
      <h1 className="page-title">{q ? `Results for "${q}"` : "Search"}</h1>
      {!q && <p className="muted">Type an album, artist or genre in the search box above.</p>}
      {artists.data && artists.data.length > 0 && (
        <nav className="filters" aria-label="Matching artists">
          {artists.data.map((a) => <Link key={a.id} to={`/artist/${a.id}`} className="filter">{a.name}</Link>)}
        </nav>
      )}
      {results.error && <ErrorNote error={results.error} />}
      {q && !results.data && results.loading && <SkeletonGrid label="Searching" />}
      {q && results.data && items.length === 0 && <p className="muted">No albums match. Check the spelling or try an artist name.</p>}
      {items.length > 0 && (
        <>
          <p className="muted">{results.data?.total} {results.data?.total === 1 ? "album" : "albums"}</p>
          <AlbumGrid albums={items} />
        </>
      )}
    </section>
  );
}
