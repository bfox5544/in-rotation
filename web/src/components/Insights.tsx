import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type ArtistStat, type Insights as Data } from "../api";
import { useFetch } from "../hooks/useFetch";
import { titleCase } from "../lib/text";
import { AlbumGrid } from "./AlbumCard";
import { Cover } from "./Cover";
import { ErrorNote, Loading } from "./Notice";
import { formatStars } from "./Stars";

const count = (n: number) => n.toLocaleString("en");
const pct = (n: number, of: number) => (of ? Math.round((100 * n) / of) : 0);
const plural = (n: number, one: string, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`;

function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months} ${months === 1 ? "month" : "months"} ago` : `${Math.floor(months / 12)}+ years ago`;
}

/** Whose profile this is: yours (Library) or someone's public profile, named rather than gendered. */
interface Subject { name: string | null }

/** One or two sentences that read the profile back. */
function summary(d: Data, { name }: Subject): string {
  const parts: string[] = [];
  const [g1, g2] = d.genres.map((g) => titleCase(g.name));
  const era = [...d.decades].sort((a, b) => b.albums - a.albums)[0];
  const genres = g2 ? `${g1} and ${g2}` : g1;
  const soft = era ? `, with a soft spot for the ${era.decade}s` : "";
  if (g1) parts.push(name ? `${name} gravitates toward ${genres}${soft}.` : `You gravitate toward ${genres}${soft}.`);
  const avg = d.overview.averageRating;
  if (avg !== null) {
    const kind = avg >= 4.2 ? "a generous rater" : avg <= 3.2 ? "a tough critic" : "a balanced rater";
    const band = d.mainstream?.band;
    parts.push(name ? `${name} is ${kind}${band ? `, with picks in ${band} territory` : ""}.`
                    : `You're ${kind}${band ? `, and your picks sit in ${band} territory` : ""}.`);
  }
  return parts.join(" ");
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

/** Horizontal bars, value at the tip; one series, so no legend. */
function BarList({ rows, label, of }: {
  rows: { key: string; name: ReactNode; value: number; text: string; art?: ReactNode }[];
  label: string;
  /** The whole that bars are a share of; the largest bar fills the track when omitted. */
  of?: number;
}) {
  const max = Math.max(1, of ?? Math.max(...rows.map((r) => r.value)));
  return (
    <ul className={rows.some((r) => r.art) ? "barlist with-art" : "barlist"} aria-label={label}>
      {rows.map((r) => (
        <li key={r.key}>
          {r.art && <span className="barlist-art">{r.art}</span>}
          <span className="barlist-name">{r.name}</span>
          <span className="barlist-track" aria-hidden="true">{r.value > 0 && <span className="barlist-bar" style={{ width: `${(100 * r.value) / max}%` }} />}</span>
          <span className="barlist-value">{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Vertical columns from one baseline. Only the tallest carries its value; every column shows its
 *  numbers on hover or focus, and the table under the chart has them all. */
function Columns({ cols, label, unit, thin = false }: {
  cols: { key: string; label: string; value: number; tip: string }[];
  label: string;
  unit: string;
  thin?: boolean;
}) {
  const max = Math.max(1, ...cols.map((c) => c.value));
  const peak = cols.findIndex((c) => c.value === max);
  return (
    <figure className="columns-figure">
      <div className={thin ? "columns thin" : "columns"} role="list" aria-label={label}>
        {cols.map((c, i) => (
          <div key={c.key} className={`col${i < cols.length / 3 ? " tip-start" : i >= (2 * cols.length) / 3 ? " tip-end" : ""}`} role="listitem" tabIndex={0} aria-label={c.tip}>
            <span className="col-tip" aria-hidden="true">{c.tip}</span>
            <span className="col-plot" aria-hidden="true">
              <span className="col-bar" style={{ height: `${(100 * c.value) / max}%` }}>
                {i === peak && c.value > 0 && !thin && <span className="col-cap">{count(c.value)}</span>}
              </span>
            </span>
            {!thin && <span className="col-label" aria-hidden="true">{c.label}</span>}
          </div>
        ))}
      </div>
      {thin && cols.length > 1 && (
        <div className="columns-ends" aria-hidden="true"><span>{cols[0].label}</span><span>{cols[cols.length - 1].label}</span></div>
      )}
      <details className="chart-table">
        <summary>Show as Table</summary>
        <table>
          <thead><tr><th scope="col">{label}</th><th scope="col">{unit}</th></tr></thead>
          <tbody>{cols.filter((c) => !thin || c.value > 0).map((c) => <tr key={c.key}><td>{c.label}</td><td>{count(c.value)}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

function ArtistName({ a }: { a: ArtistStat | { id: string | null; name: string } }) {
  return a.id ? <Link to={`/artist/${a.id}`}>{a.name}</Link> : <>{a.name}</>;
}

function Section({ title, note, children, wide = false }: { title: string; note?: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={wide ? "insight wide" : "insight"}>
      <h2>{title}</h2>
      {note && <p className="insight-note">{note}</p>}
      {children}
    </section>
  );
}

/** Your own Insights (Library tab): ratings, saves and recommendation stats. */
export function Insights() {
  const res = useFetch(api.insights, []);
  if (res.error) return <ErrorNote error={res.error} />;
  if (!res.data) return <Loading label="Building your profile" />;
  return <InsightsView d={res.data} subject={{ name: null }} />;
}

/** Someone's public Insights (ADR 0018): built from their ratings only. */
export function ProfileInsights({ username, name, isYou }: { username: string; name: string; isYou: boolean }) {
  const res = useFetch(() => api.profileInsights(username), [username]);
  if (res.error) return <ErrorNote error={res.error} />;
  if (!res.data) return <Loading label="Building the profile" />;
  if (res.data.overview.albumsRated < 3) {
    return (
      <div className="insights-empty">
        <p className="muted">
          {isYou ? <>Rate a few more albums and your Insights appear here. <Link to="/start">Choose albums you know</Link>.</>
                 : `${name} hasn't rated enough albums for Insights yet.`}
        </p>
      </div>
    );
  }
  return <InsightsView d={res.data} subject={{ name }} />;
}

function InsightsView({ d, subject }: { d: Data; subject: Subject }) {
  const o = d.overview;
  const who = subject.name;
  if (o.albumsRated < 3) {
    return (
      <div className="insights-empty">
        <h2>Your Music Profile Starts Here</h2>
        <p className="muted">Rate a few albums and this tab turns your ratings into a picture of your taste. <Link to="/start">Choose albums you know</Link>.</p>
      </div>
    );
  }
  const r = d.recommendations;
  const ratedCount = d.ratings.reduce((n, x) => n + x.albums, 0);
  return (
    <div className="insights">
      <header className="profile">
        <div className="profile-covers" aria-hidden="true">
          {d.topAlbums.slice(0, 5).map((t) => <Cover key={t.album.id} album={t.album} />)}
        </div>
        <div className="profile-copy">
          <h2 className="profile-title">{who ? "Music Profile" : "Your Music Profile"}</h2>
          <p className="profile-summary">{summary(d, subject)}</p>
        </div>
        <div className="stats">
          <Stat value={count(o.albumsRated)} label="Albums Rated" />
          <Stat value={count(o.artistsExplored)} label="Artists Explored" />
          <Stat value={o.averageRating !== null ? `★ ${o.averageRating.toFixed(1)}` : "–"} label="Average Rating" />
          <Stat value={count(o.genresExplored)} label="Genres Explored" />
        </div>
      </header>

      <div className="insight-grid">
        <Section title="Top Genres" note={`Share of the ${plural(o.albumsRated, "album")} ${who ? `${who} has rated` : "you've rated"}. An album counts toward up to three genres.`}>
          <BarList label="Top genres" rows={d.genres.map((g) => ({
            key: g.name, name: titleCase(g.name), value: g.albums, text: `${Math.round(g.share * 100)}%`,
          }))} />
        </Section>

        <Section title="Rating Habits" note={o.averageRating !== null ? `${plural(ratedCount, "rating")}, averaging ${formatStars(Math.round(o.averageRating * 2) / 2)} stars.` : undefined}>
          <Columns label="Stars" unit="Albums" cols={d.ratings.map((x) => ({
            key: String(x.stars), label: formatStars(x.stars), value: x.albums,
            tip: `${formatStars(x.stars)} stars: ${plural(x.albums, "album")}`,
          }))} />
        </Section>

        <Section title="Favorite Artists" note="Highest average rating.">
          <ul className="artist-list">
            {d.favoriteArtists.map((a) => (
              <li key={a.id ?? a.name}>
                <Link to={`/album/${a.album.id}`} className="artist-art" aria-label={`${a.album.title} by ${a.name}`}><Cover album={a.album} /></Link>
                <span className="artist-name"><ArtistName a={a} /></span>
                <span className="artist-meta">★ {formatStars(Math.round((a.averageRating ?? 0) * 2) / 2)}<span className="soft"> {plural(a.albums, "album")}</span></span>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Most Rated" note={`Artists with the most albums ${who ? `${who} has rated` : "you've rated"}.`}>
          <BarList label="Most rated artists" rows={d.topArtists.map((a) => ({
            key: a.id ?? a.name, name: <ArtistName a={a} />, value: a.albums, text: count(a.albums),
            art: <Cover album={a.album} />,
          }))} />
        </Section>

        <Section title="Eras" note={d.decades.length ? `${who ? `${who}'s ratings span` : "Your ratings span"} ${d.years[0]?.year} to ${d.years[d.years.length - 1]?.year}.` : undefined} wide>
          <div className="eras">
            <Columns label="Decade" unit="Albums" cols={d.decades.map((e) => ({
              key: String(e.decade), label: `${e.decade}s`, value: e.albums,
              tip: `${e.decade}s: ${plural(e.albums, "album")}${e.averageRating !== null ? `, average ${e.averageRating.toFixed(1)} stars` : ""}`,
            }))} />
            <div className="eras-years">
              <h3>Release Years</h3>
              <Columns thin label="Year" unit="Albums" cols={d.years.map((y) => ({
                key: String(y.year), label: String(y.year), value: y.albums, tip: `${y.year}: ${plural(y.albums, "album")}`,
              }))} />
            </div>
          </div>
        </Section>
      </div>

      <Section title="Highest Rated" wide>
        <AlbumGrid albums={d.topAlbums.slice(0, 8).map((t) => t.album)}
          detail={(a) => `★ ${formatStars(d.topAlbums.find((t) => t.album.id === a.id)!.rating)}`} />
      </Section>

      <Section title="Recently Rated" wide>
        <AlbumGrid albums={d.recentAlbums.slice(0, 8).map((x) => x.album)} detail={(a) => {
          const x = d.recentAlbums.find((e) => e.album.id === a.id)!;
          return `Rated ★ ${formatStars(x.rating)} ${ago(x.at)}`;
        }} />
        {d.newArtists.length > 0 && (
          <>
            <h3 className="insight-sub">{who ? "Newest Artists" : "Newest Artists in Your Ratings"}</h3>
            <ul className="artist-chips">
              {d.newArtists.map((a) => (
                <li key={a.id ?? a.name}>
                  <span className="artist-chip-art" aria-hidden="true"><Cover album={a.album} /></span>
                  <span><ArtistName a={a} /><span className="soft">{ago(a.at)}</span></span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {r && <Section title="Recommendations" wide
        note={r.shown ? `Since ${new Date(r.since!).toLocaleDateString("en", { month: "long", day: "numeric" })}: ${plural(r.forYou, "album")} on For You and ${plural(r.ask, "album")} from Ask.`
                      : "Counting starts with your next visit to For You or Ask."}>
        {r.shown > 0 && (
          <div className="recs">
            <div className="stats compact">
              <Stat value={count(r.shown)} label="Recommended" />
              <Stat value={`${pct(r.liked, r.shown)}%`} label="Liked (4★ and Up)" />
              <Stat value={count(r.saved)} label="Saved" />
              <Stat value={count(r.dismissed)} label="Not for Me" />
            </div>
            <BarList label="What happened to recommendations" of={r.shown} rows={[
              { key: "rated", name: "Rated", value: r.rated, text: `${count(r.rated)} (${pct(r.rated, r.shown)}%)` },
              { key: "liked", name: "Liked", value: r.liked, text: `${count(r.liked)} (${pct(r.liked, r.shown)}%)` },
              { key: "saved", name: "Saved", value: r.saved, text: `${count(r.saved)} (${pct(r.saved, r.shown)}%)` },
              { key: "dismissed", name: "Dismissed", value: r.dismissed, text: `${count(r.dismissed)} (${pct(r.dismissed, r.shown)}%)` },
            ]} />
          </div>
        )}
      </Section>}
    </div>
  );
}
