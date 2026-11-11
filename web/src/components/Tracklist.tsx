import type { Tracklist as TracklistData } from "../api";

function duration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function runtime(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
}

export function Tracklist({ tracklist }: { tracklist: TracklistData }) {
  const tracks = tracklist.discs.flatMap((d) => d.tracks);
  const timed = tracks.filter((t) => t.seconds !== null);
  const total = timed.reduce((sum, t) => sum + (t.seconds ?? 0), 0);
  const several = tracklist.discs.length > 1;
  return (
    <section className="tracklist" aria-labelledby="tracks-heading">
      <h2 id="tracks-heading">Tracks</h2>
      <p className="tracklist-summary">
        {tracks.length} {tracks.length === 1 ? "track" : "tracks"}
        {timed.length === tracks.length && total > 0 && <>, {runtime(total)}</>}
      </p>
      {tracklist.discs.map((disc) => (
        <div key={disc.position} className="disc">
          {several && (
            <h3 className="disc-heading">
              Disc {disc.position}
              {disc.title && <span className="disc-title">{disc.title}</span>}
            </h3>
          )}
          <ol className="tracks">
            {disc.tracks.map((t, i) => (
              <li key={i} className="track">
                <span className="track-number">{t.number}</span>
                <span className="track-title">
                  {t.title}
                  {t.artist && <span className="track-artist">{t.artist}</span>}
                </span>
                <span className="track-length">{t.seconds !== null ? duration(t.seconds) : ""}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
      <p className="tracklist-source">
        Track list from <a href={`https://musicbrainz.org/release/${tracklist.releaseId}`} target="_blank" rel="noreferrer">MusicBrainz</a>
      </p>
    </section>
  );
}
