import type { ReactNode } from "react";
import type { Album } from "../types";

/** The services' own marks, drawn simply in their brand colours (solid, no gradients). */
const SpotifyIcon = (
  <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
    <circle cx="12" cy="12" r="12" fill="#1ed760" />
    <path d="M6.2 9.4c3.9-1.2 8.2-.8 11.6 1.1M6.9 12.6c3.2-.9 6.6-.6 9.4 1M7.6 15.6c2.5-.7 5.1-.4 7.2.8" fill="none"
      stroke="#121212" strokeWidth="1.7" strokeLinecap="round" />
  </svg>
);

const AppleMusicIcon = (
  <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
    <rect width="24" height="24" rx="6" fill="#fa2d48" />
    <path d="M9.6 16.4V7.6l7-1.5v8.6" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
    <ellipse cx="8" cy="16.6" rx="2" ry="1.6" fill="#fff" />
    <ellipse cx="15" cy="14.9" rx="2" ry="1.6" fill="#fff" />
  </svg>
);

/** "Listen On" icons for the album page (ADR 0016). Each goes through the API, which opens the regular
 *  album on the service (never a deluxe or other edition) or, failing that, the service's search. */
export function StreamingLinks({ album }: { album: Album }) {
  const services: { name: string; path: string; icon: ReactNode }[] = [
    { name: "Spotify", path: "spotify", icon: SpotifyIcon },
    { name: "Apple Music", path: "apple-music", icon: AppleMusicIcon },
  ];
  return (
    <p className="listen-on">
      <span className="listen-label">Listen On</span>
      {services.map((s) => (
        <a key={s.name} href={`/api/albums/${encodeURIComponent(album.id)}/listen/${s.path}`} target="_blank"
          rel="noopener noreferrer" className="listen-link" title={s.name}
          aria-label={`Open ${album.title} on ${s.name} (new tab)`}>
          {s.icon}
        </a>
      ))}
    </p>
  );
}
