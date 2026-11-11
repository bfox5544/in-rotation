import { useState } from "react";
import type { Album } from "../types";

/** The album's cover from the API's cover cache (ADR 0011). A neutral tile holds the space until
 *  the image arrives, then it fades in. Albums with no archived art say so plainly. */
export function Cover({ album }: { album: Album }) {
  const [failed, setFailed] = useState(false);   // the Cover Art Archive has no image for some albums
  const [loaded, setLoaded] = useState(false);
  if (album.coverUrl && !failed) {
    return (
      <span className="cover cover-frame">
        <img className={loaded ? "cover-img loaded" : "cover-img"} src={album.coverUrl} alt={`${album.title} by ${album.artist}`}
          width={250} height={250} loading="lazy" decoding="async"
          onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
      </span>
    );
  }
  return (
    <span className="cover cover-frame cover-missing" role="img" aria-label={`${album.title} by ${album.artist}, no cover available`}>
      <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="12" cy="12" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <span>No Cover</span>
    </span>
  );
}
