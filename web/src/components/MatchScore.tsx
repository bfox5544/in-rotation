import { Link } from "react-router-dom";
import { api, type Match } from "../api";
import type { Album } from "../types";
import { useFetch } from "../hooks/useFetch";
import { useLibrary } from "../state/library";

const and = (names: string[]) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0]);

const stop = (text: string) => (/[.!?]$/.test(text) ? text : `${text}.`);

/** Which rated albums it's closest to. The listener counts aren't shown (owner request 2026-11-10). */
function sentence(m: Match): string {
  return m.alongside.length ? stop(`Most like ${and(m.alongside.map((a) => a.title))} of the albums you rated`) : "";
}

/** "92 Match" on album pages (ADR 0019, revised for item kNN, ADR 0028): where this album's similarity to
 *  the albums you rated ranks among the albums listeners who share your taste have. Refetched when your
 *  taste changes. */
export function MatchScore({ album }: { album: Album }) {
  const { rated, ratingOf, whenSynced } = useLibrary();
  // Only ratings of 3 stars and up shape the taste; this album's own rating is left out by the API.
  const taste = rated.filter((r) => r.rating >= 3 && r.album.id !== album.id).map((r) => `${r.album.id}:${r.rating}`).sort().join();
  const res = useFetch(async () => {
    await whenSynced();
    return api.match(album.id);
  }, [album.id, taste]);
  const m = res.data;
  if (!m) return <div className="match match-pending" aria-hidden="true" />;

  let body;
  if (m.status === "ok" && m.score !== null) {
    body = (
      <>
        <div className="match-score" role="img" aria-label={`${m.score} out of 100 match with your taste`}>
          <span className="match-value">{m.score}</span>
          <span className="match-label">Match</span>
          <span className="match-meter" aria-hidden="true"><span style={{ width: `${m.score}%` }} /></span>
        </div>
        <p className="match-why">
          {[sentence(m), ratingOf(album.id) !== null ? "Scored as if you hadn't rated it." : ""].filter(Boolean).join(" ")}
        </p>
      </>
    );
  } else if (m.status === "no_taste") {
    body = <p className="match-why">Rate a few albums 3 stars or more to see how well this one matches your taste. <Link to="/start">Rate albums you know</Link></p>;
  } else if (m.status === "not_in_data") {
    body = <p className="match-why">No match score. This album isn't in the listening data.</p>;
  } else {
    body = <p className="match-why">No match score. Too few people who share your taste have this album to score it.</p>;
  }
  return (
    <section className="match" aria-label="Match with your taste">
      {body}
      <details className="match-how">
        <summary>How Match Works</summary>
        <p>
          Two albums are similar when the same people in the listening data rank both near the top of their lists.
          This album's similarity to each album you rated 3 stars or more is added up, and the score is where that
          total ranks among the albums at least 0.1% of the listeners who have your albums also have. 92 means it ranks
          above 92% of them. A smaller album is scored when 5% of its own listeners have your albums. It shows how close the album is to your taste, not the stars you would give it.
        </p>
      </details>
    </section>
  );
}
