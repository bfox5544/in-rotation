import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useLibrary } from "../state/library";
import { api, ApiError, type PublicProfile } from "../api";
import { AlbumGrid } from "../components/AlbumCard";
import { Avatar } from "../components/Avatar";
import { ProfileInsights } from "../components/Insights";
import { ProfileSettings } from "../components/ProfileSettings";
import { ErrorNote, Loading } from "../components/Notice";
import { formatStars } from "../components/Stars";
import { Tabs, useTab } from "../components/Tabs";
import { useFetch } from "../hooks/useFetch";

const TABS = [{ key: "ratings", label: "Ratings" }, { key: "insights", label: "Insights" }];
const OWNER_TABS = [...TABS, { key: "settings", label: "Settings" }];
const PAGE = 48;
type Order = "newest" | "highest";

/** /u/:username, someone's profile (ADR 0018): name, picture, ratings, and Insights from those ratings.
 *  An account is a profile, so on your own page a Settings tab holds the account and profile settings. */
export default function Profile() {
  const { username = "" } = useParams();
  const { profile: mine } = useLibrary();
  const res = useFetch(() => api.profile(username), [username]);
  const [asked, select] = useTab(OWNER_TABS);

  if (res.error) {
    if (res.error instanceof ApiError && res.error.status === 404) {
      return (
        <section className="section">
          <h1 className="page-title">Profile Not Found</h1>
          <p className="muted">There's no public profile at @{username}. It may have been renamed or made private.</p>
        </section>
      );
    }
    return <section className="section"><ErrorNote error={res.error} /></section>;
  }
  if (!res.data) return <section className="section"><Loading label="Loading the profile" /></section>;
  // Your own header follows your settings as you change them.
  const p = res.data.isYou && mine
    ? { ...res.data, displayName: mine.displayName, avatarUrl: mine.avatarUrl, public: mine.public } : res.data;
  const tabs = p.isYou ? OWNER_TABS : TABS;
  const tab = tabs.some((t) => t.key === asked) ? asked : "ratings";
  return (
    <>
      <section className="section library-head">
        <ProfileHead p={p} onEdit={() => select("settings")} />
        <Tabs tabs={tabs} tab={tab} select={select} label="Profile" />
      </section>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "insights" ? <ProfileInsights username={p.username} name={p.displayName} isYou={p.isYou} />
          : tab === "settings" ? (mine ? <ProfileSettings key={mine.username} /> : <section className="section"><Loading /></section>)
          : <Ratings p={p} />}
      </div>
    </>
  );
}

function ProfileHead({ p, onEdit }: { p: PublicProfile; onEdit: () => void }) {
  const [copied, setCopied] = useState(false);
  const since = new Date(p.memberSince).toLocaleDateString("en", { month: "long", year: "numeric" });
  const copy = () => {
    navigator.clipboard?.writeText(window.location.href.split("?")[0]).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }, () => undefined);
  };
  return (
    <header className="user-head">
      <Avatar url={p.avatarUrl} name={p.displayName} size={112} />
      <div className="user-head-copy">
        <h1 className="page-title">{p.displayName}</h1>
        <p className="user-handle">@{p.username}</p>
        <p className="muted user-since">Member since {since}</p>
      </div>
      {p.isYou && (
        <div className="user-head-actions">
          <button type="button" className="btn btn-quiet btn-small" onClick={onEdit}>Edit Profile</button>
          {p.public && (
            <button type="button" className="btn btn-quiet btn-small" onClick={copy}>{copied ? "Link Copied" : "Copy Link"}</button>
          )}
        </div>
      )}
      {p.isYou && !p.public && (
        <p className="notice user-private" role="status">Your profile is private: only you can see this page. Turn on Public Profile in Settings to share it.</p>
      )}
    </header>
  );
}

function Ratings({ p }: { p: PublicProfile }) {
  const [order, setOrder] = useState<Order>("newest");
  const [shown, setShown] = useState(PAGE);
  if (p.ratings.length === 0) {
    return (
      <section className="section">
        <p className="muted">
          {p.isYou ? <>You haven't rated anything yet. <Link to="/start">Rate albums you know</Link>.</> : `${p.displayName} hasn't rated any albums yet.`}
        </p>
      </section>
    );
  }
  // The server sends newest first; a stable sort keeps that order among equal ratings.
  const sorted = order === "newest" ? p.ratings : [...p.ratings].sort((a, b) => b.rating - a.rating);
  const stars = new Map(p.ratings.map((r) => [r.album.id, r.rating]));
  const visible = sorted.slice(0, shown);
  const n = p.ratings.length;
  return (
    <section className="section">
      <div className="toolbar">
        <div className="toolbar-status">
          <p className="toolbar-count">{n.toLocaleString("en")} {n === 1 ? "Album" : "Albums"} Rated</p>
        </div>
        <div className="toolbar-actions">
          <label className="sort">
            <span className="visually-hidden">Order</span>
            <select value={order} onChange={(e) => { setOrder(e.target.value as Order); setShown(PAGE); }}>
              <option value="newest">Newest First</option>
              <option value="highest">Highest Rated</option>
            </select>
          </label>
        </div>
      </div>
      {!p.isYou && (
        <p className="muted toolbar-note">Stars under each cover are {p.displayName}'s ratings. The badge on a cover is your own.</p>
      )}
      <AlbumGrid albums={visible.map((r) => r.album)} detail={(a) => `★ ${formatStars(stars.get(a.id) ?? 0)}`} />
      {visible.length < n && (
        <div className="browse-more">
          <button type="button" className="btn btn-quiet" onClick={() => setShown(shown + PAGE)}>
            Show More ({(n - visible.length).toLocaleString("en")} Left)
          </button>
        </div>
      )}
    </section>
  );
}
