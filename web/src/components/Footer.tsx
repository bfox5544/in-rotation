import { Link, useLocation } from "react-router-dom";

const HOW = "/how-recommendations-work";
const LINKS = [
  { to: "/contact", label: "Contact" },
  { to: "/data-sources", label: "Data Sources" },
  { to: "/privacy", label: "Privacy" },
  { to: HOW, label: "How Recommendations Work" },
  { to: `${HOW}?tab=technical`, label: "How Model Was Chosen" },
];

/** The footer on every page (rendered once by App, below <main>). The app keeps the scroll position
 *  between pages, so these links start the new page at the top. Two links share a path and differ by
 *  tab, so "active" compares the tab too (NavLink would mark both). */
export function Footer() {
  const { pathname, search } = useLocation();
  const toTop = () => window.scrollTo({ top: 0 });
  const isActive = (to: string) => {
    const [path, query = ""] = to.split("?");
    const tab = new URLSearchParams(query).get("tab");
    const current = new URLSearchParams(search).get("tab") === "technical" ? "technical" : null;   // Overview may be ?tab=overview
    return pathname === path && current === tab;
  };
  return (
    <footer className="footer">
      <div className="footer-inner">
        <p className="footer-brand">
          <span className="footer-name">In Rotation</span>
          <span>© {new Date().getFullYear()}</span>
        </p>
        <nav className="footer-links" aria-label="Site information">
          {LINKS.map((l) => {
            const on = isActive(l.to);
            return (
              <Link key={l.to} to={l.to} onClick={toTop} className={on ? "active" : undefined} aria-current={on ? "page" : undefined}>
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <p className="footer-note">
        Album artwork belongs to its respective owners and is shown only to identify each album.
      </p>
    </footer>
  );
}
