import { titleCase } from "../lib/text";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { useFetch } from "../hooks/useFetch";
import { Cover } from "../components/Cover";
import { AlbumGrid } from "../components/AlbumCard";
import { ErrorNote, SkeletonDetail } from "../components/Notice";
import { ListMenu } from "../components/ListMenu";
import { MatchScore } from "../components/MatchScore";
import { Stars } from "../components/Stars";
import { StreamingLinks } from "../components/StreamingLinks";
import { Tracklist } from "../components/Tracklist";
import { useLibrary } from "../state/library";

export default function AlbumDetail() {
  const { id = "" } = useParams();
  const detail = useFetch(() => api.album(id), [id]);
  const { isLater, toggleLater } = useLibrary();
  if (detail.error instanceof ApiError && detail.error.status === 404) {
    return (
      <section className="section">
        <h1 className="page-title">Album Not Found</h1>
        <p className="muted">It may have been removed. <Link to="/">Back to Discover</Link></p>
      </section>
    );
  }
  if (detail.error) return <section className="section"><ErrorNote error={detail.error} /></section>;
  if (!detail.data) return <SkeletonDetail />;
  const { album, similar, tracklist } = detail.data;
  return (
    <>
      <section className="detail">
        <div className="detail-art"><Cover album={album} /></div>
        <div className="detail-copy">
          <h1>{album.title}</h1>
          <p className="detail-artist">
            {album.artistId ? <Link to={`/artist/${album.artistId}`}>{album.artist}</Link> : album.artist}
          </p>
          <dl className="facts">
            {album.year && <div><dt>Released</dt><dd>{album.year}</dd></div>}
            {album.genres.length > 0 && <div><dt>Genres</dt><dd>{album.genres.map(titleCase).join(", ")}</dd></div>}
          </dl>
          <MatchScore album={album} />
          <Stars album={album} />
          <div className="detail-actions">
            <button className="btn" onClick={() => toggleLater(album)} aria-pressed={isLater(album.id)}>
              {isLater(album.id) ? "Remove from Listen Later" : "Listen Later"}
            </button>
            <ListMenu album={album} />
          </div>
          <StreamingLinks album={album} />
          <Link to={`/map?album=${album.id}`} className="map-link">See It on the Album Map</Link>
          {tracklist && <Tracklist tracklist={tracklist} />}
        </div>
      </section>
      {similar.length > 0 && (
        <section className="section">
          <h2>Listeners Also Love</h2>
          <AlbumGrid albums={similar} />
        </section>
      )}
    </>
  );
}
