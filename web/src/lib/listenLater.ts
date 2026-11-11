import type { Album } from "../types";

/** Albums in Listen Later this long without a rating get a "Listened yet?" prompt. */
export const WAIT_DAYS = 7;
const DAY = 86_400_000;

/** Unrated albums saved at least WAIT_DAYS ago, longest waiting first. */
export function waiting(later: Album[], added: Record<string, string>, ratingOf: (id: string) => number | null, now = Date.now()): Album[] {
  const at = (a: Album) => (added[a.id] ? Date.parse(added[a.id]) : now);
  return later.filter((a) => ratingOf(a.id) === null && now - at(a) >= WAIT_DAYS * DAY).sort((a, b) => at(a) - at(b));
}

/** "3 days ago", "2 weeks ago", "4 months ago". */
export function since(iso: string | undefined, now = Date.now()): string {
  if (!iso) return "";
  const days = Math.floor((now - Date.parse(iso)) / DAY);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  const years = Math.floor(days / 365);
  return years === 1 ? "a year ago" : `${years} years ago`;
}
