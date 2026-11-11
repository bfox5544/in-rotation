import { useState } from "react";
import { Link } from "react-router-dom";
import type { Album } from "../types";

/** A 2 x 2 image of a list's first four albums. Empty corners stay as plain tiles. */
export function ListArt({ albums }: { albums: Album[] }) {
  return (
    <span className="list-art" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => <ArtCell key={albums[i]?.id ?? `empty-${i}`} album={albums[i]} />)}
    </span>
  );
}

function ArtCell({ album }: { album: Album | undefined }) {
  const [failed, setFailed] = useState(false);
  if (!album?.coverUrl || failed) return <span className="list-art-cell" />;
  return (
    <span className="list-art-cell">
      <img src={album.coverUrl} alt="" width={125} height={125} loading="lazy" decoding="async" onError={() => setFailed(true)} />
    </span>
  );
}

/** One list in the Library: its image, name and size, linking to the list's own page. */
export function ListTile({ to, name, albums }: { to: string; name: string; albums: Album[] }) {
  const n = albums.length;
  return (
    <article className="list-tile">
      <Link to={to} className="list-tile-link">
        <ListArt albums={albums} />
        <span className="card-title">{name}</span>
      </Link>
      <p className="card-artist">{n === 0 ? "Empty" : `${n.toLocaleString("en")} ${n === 1 ? "Album" : "Albums"}`}</p>
    </article>
  );
}
