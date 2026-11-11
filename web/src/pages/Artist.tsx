import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { useFetch } from "../hooks/useFetch";
import { AlbumGrid } from "../components/AlbumCard";
import { ErrorNote, SkeletonPage } from "../components/Notice";

export default function ArtistPage() {
  const { id = "" } = useParams();
  const page = useFetch(() => api.artist(id), [id]);
  if (page.error instanceof ApiError && page.error.status === 404) {
    return (
      <section className="section">
        <h1 className="page-title">Artist Not Found</h1>
        <p className="muted"><Link to="/">Back to Discover</Link></p>
      </section>
    );
  }
  if (page.error) return <section className="section"><ErrorNote error={page.error} /></section>;
  if (!page.data) return <SkeletonPage label="Loading artist" />;
  const { artist, albums, other, related } = page.data;
  return (
    <>
      <section className="artist-head">
        <h1 className="page-title">{artist.name}</h1>
        <p className="muted">Most listened first.</p>
        {albums.length > 0 && <AlbumGrid albums={albums} />}
      </section>
      {other.length > 0 && (
        <section className="section">
          <h2>{albums.length > 0 ? "EPs, Live and Other Releases" : "Releases"}</h2>
          <AlbumGrid albums={other} />
        </section>
      )}
      {related.length > 0 && (
        <section className="section">
          <h2>Their Listeners Also Play</h2>
          <AlbumGrid albums={related.map((r) => r.album)} />
        </section>
      )}
    </>
  );
}
