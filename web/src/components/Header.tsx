import { NavLink } from "react-router-dom";
import { useLibrary } from "../state/library";
import { Avatar } from "./Avatar";
import { SearchBox } from "./SearchBox";

export function Header() {
  const { rated, email, profile } = useLibrary();
  // Rated albums only. Listen Later and custom lists don't count (owner decision 2026-11-04).
  const saved = rated.length;
  return (
    <header className="header">
      <NavLink to="/" className="brand">In Rotation</NavLink>
      <SearchBox />
      <nav className="nav" aria-label="Main">
        <NavLink to="/">Discover</NavLink>
        <NavLink to="/library">{saved > 0 ? `Library (${saved})` : "Library"}</NavLink>
        <NavLink to="/for-you">For You</NavLink>
        <NavLink to="/map">Map</NavLink>
        <NavLink to="/ask">Ask</NavLink>
        {/* An account is a profile (ADR 0018); /account is sign-in for everyone else. */}
        {email && profile ? (
          <NavLink to={`/u/${profile.username}`} className="nav-profile">
            <Avatar url={profile.avatarUrl} name={profile.displayName} size={22} />
            Profile
          </NavLink>
        ) : (
          <NavLink to="/account">{email ? "Profile" : "Sign In"}</NavLink>
        )}
      </nav>
    </header>
  );
}
