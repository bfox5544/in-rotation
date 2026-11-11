import { Link } from "react-router-dom";
import type { Album } from "../types";
import { Cover } from "./Cover";
import { CloseIcon } from "./Icons";
import { RatingBadge } from "./RatingBadge";
import { SaveMenu } from "./SaveMenu";

/** detail: an optional third caption line, such as the year or a rating. */
export function AlbumCard({ album, onDismiss, detail }: { album: Album; onDismiss?: (album: Album) => void; detail?: string | null }) {
  return (
    <article className="card">
      <div className="card-art">
        <Link to={`/album/${album.id}`} aria-label={`${album.title} by ${album.artist}`}>
          <Cover album={album} />
        </Link>
        <RatingBadge album={album} />
        {onDismiss && (
          <button type="button" className="chip card-dismiss" aria-label={`Don't suggest ${album.title}`}
            title="Don't suggest this" onClick={() => onDismiss(album)}>
            <CloseIcon />
          </button>
        )}
        <div className="card-actions">
          <SaveMenu album={album} />
        </div>
      </div>
      <Link to={`/album/${album.id}`} className="card-title" title={album.title.length > 60 ? album.title : undefined}>{album.title}</Link>
      <p className="card-artist">
        {album.artistId ? <Link to={`/artist/${album.artistId}`}>{album.artist}</Link> : album.artist}
      </p>
      {detail && <p className="card-detail">{detail}</p>}
    </article>
  );
}

export function AlbumGrid({ albums, onDismiss, detail }: {
  albums: Album[];
  onDismiss?: (album: Album) => void;
  detail?: (album: Album) => string | null | undefined;
}) {
  return (
    <div className="grid">
      {albums.map((a) => (
        <AlbumCard key={a.id} album={a} onDismiss={onDismiss} detail={detail?.(a)} />
      ))}
    </div>
  );
}
