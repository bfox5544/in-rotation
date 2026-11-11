import type { AlbumQuery } from "../api";
import type { Album } from "../types";

/** Catalog filters as they appear in the home page and For You URLs (ADR 0015, 0026). All optional; they combine.
 *  length is For You only. */
export const FILTER_KEYS = ["genre", "decade", "year", "popularity", "country", "type", "length", "sort"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string>>;

export function readFilters(params: URLSearchParams): Filters {
  const out: Filters = {};
  for (const k of FILTER_KEYS) {
    const v = params.get(k);
    if (v) out[k] = v;
  }
  return out;
}

export function writeFilters(params: URLSearchParams, filters: Filters): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const k of FILTER_KEYS) {
    if (filters[k]) next.set(k, filters[k]!);
    else next.delete(k);
  }
  return next;
}

/** The filters For You offers (ADR 0026): genre, decade, album length and type. Its How Well Known slider
 *  stands in for Popularity, and it has no sort. */
export const FOR_YOU_KEYS: FilterKey[] = ["genre", "decade", "length", "type"];
export const forYouFilters = (f: Filters): Filters =>
  Object.fromEntries(FOR_YOU_KEYS.filter((k) => f[k]).map((k) => [k, f[k]]));

/** Filters that narrow the list (the sort only orders it). */
export const activeCount = (f: Filters) => FILTER_KEYS.filter((k) => k !== "sort" && f[k]).length;

/** Toolbar sort choices; "popular" is the default and stays out of the URL. */
export const SORT_LABELS: Record<string, string> = {
  popular: "Most Popular",
  newest: "Newest",
  oldest: "Oldest",
  rated: "Highest Rated",
  title: "Title A to Z",
};

/** The /albums query: an exact year replaces the decade. */
export function toQuery(f: Filters): AlbumQuery {
  const year = Number(f.year);
  const decade = Number(f.decade);
  const span = f.year && Number.isInteger(year) ? [year, year] : f.decade && Number.isInteger(decade) ? [decade, decade + 9] : null;
  return {
    genre: f.genre,
    year_from: span?.[0],
    year_to: span?.[1],
    popularity: f.popularity,
    country: f.country,
    type: f.type,
    length: f.length,
    sort: f.sort,
  };
}

export const count = (n: number) => n.toLocaleString("en");

const regionNames = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    return null;
  }
})();
// MusicBrainz uses a few codes outside ISO 3166 for areas that aren't countries.
const SPECIAL_REGIONS: Record<string, string> = { XW: "Worldwide", XE: "Europe", XU: "Unknown country" };

export function countryName(code: string): string {
  if (SPECIAL_REGIONS[code]) return SPECIAL_REGIONS[code];
  try {
    return regionNames?.of(code) ?? code;
  } catch {
    return code;
  }
}

/** The card's third caption line: the rating when sorting by it, otherwise the year. */
export function cardDetail(sort: string | undefined) {
  return (a: Album) => {
    if (sort === "rated") {
      if (!a.rating) return "No rating yet";
      return `★ ${a.rating.toFixed(1)} from ${count(a.ratingVotes ?? 0)} ${a.ratingVotes === 1 ? "vote" : "votes"}`;
    }
    return a.year ? String(a.year) : null;
  };
}
