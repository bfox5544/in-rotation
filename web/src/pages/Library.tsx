import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AlbumGrid } from "../components/AlbumCard";
import { Insights } from "../components/Insights";
import { ListTile } from "../components/ListTile";
import { SkeletonGrid } from "../components/Notice";
import { waiting, WAIT_DAYS } from "../lib/listenLater";
import { Tabs, useTab } from "../components/Tabs";
import { StarGlyphs, formatStars, starLabel } from "../components/Stars";
import { useLibrary } from "../state/library";

const TABS = [{ key: "collection", label: "Collection" }, { key: "insights", label: "Insights" }];

/** Library has two tabs: what you've rated and saved, and Insights, a profile drawn from it (ADR 0017). */
export default function Library() {
  const [tab, select] = useTab(TABS);
  return (
    <>
      <section className="section library-head">
        <h1 className="page-title">Your Library</h1>
        <Tabs tabs={TABS} tab={tab} select={select} label="Library" />
      </section>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "insights" ? <Insights /> : <Collection />}
      </div>
    </>
  );
}

function Collection() {
  const { rated, later, laterAdded, lists, email, loaded, error, ratingOf, createList } = useLibrary();
  const stale = waiting(later, laterAdded, ratingOf).length;
  const [name, setName] = useState("");
  const create = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createList(name.trim()).catch(() => undefined);
    setName("");
  };
  // Highest first; ties keep the newest-first order from the server.
  const byStars = [...new Set(rated.map((r) => r.rating))].sort((a, b) => b - a);
  return (
    <>
      <section className="section">
        <h2>Your Ratings</h2>
        {!email && (rated.length > 0 || later.length > 0) && (
          <p className="muted">This library lives in this browser. <Link to="/account">Create an account</Link> to keep it.</p>
        )}
        {!loaded && !error ? (
          <SkeletonGrid count={6} label="Loading your library" />
        ) : rated.length === 0 ? (
          <p className="muted">Nothing rated yet. <Link to="/start">Rate albums you know</Link> or use the stars on any album page.</p>
        ) : (
          byStars.map((stars) => (
            <div key={stars} className="rated-group">
              <h2 className="rated-heading">
                <StarGlyphs value={stars} size={20} />
                <span><strong>{formatStars(stars)}</strong> {starLabel(stars)}</span>
              </h2>
              <AlbumGrid albums={rated.filter((r) => r.rating === stars).map((r) => r.album)} />
            </div>
          ))
        )}
      </section>
      <section className="section">
        <h2>Your Lists</h2>
        {stale > 0 && (
          <p className="nudge">
            {stale === 1 ? "One album has" : `${stale} albums have`} waited in Listen Later for over {WAIT_DAYS === 7 ? "a week" : `${WAIT_DAYS} days`}.
            {" "}<Link to="/library/listen-later">Listened yet? Rate {stale === 1 ? "it" : "them"}</Link>
          </p>
        )}
        <div className="grid list-grid">
          <ListTile to="/library/listen-later" name="Listen Later" albums={later} />
          {lists.map((l) => <ListTile key={l.id} to={`/library/lists/${l.id}`} name={l.name} albums={l.albums} />)}
        </div>
        <form onSubmit={create} className="list-new list-new-wide">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
            placeholder="Name a new list, like Sunday mornings" aria-label="New list name" />
          <button className="btn" type="submit" disabled={!name.trim()}>Create List</button>
        </form>
      </section>
    </>
  );
}
