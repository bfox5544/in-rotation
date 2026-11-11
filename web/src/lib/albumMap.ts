import type { AlbumMapData } from "../api";
import type { Album } from "../types";

/** The map's coordinates run 0..WORLD on the longer side (ingest.album_map, ADR 0022). */
export const WORLD = 1000;
const CELL = 10;                       // grid bucket size in map units, for hit tests and culling
const SIDE = WORLD / CELL;

export interface MapModel {
  n: number;
  ids: string[];
  titles: string[];
  artists: string[];
  years: (number | null)[];
  listeners: number[];
  xs: Float32Array;
  ys: Float32Array;
  /** dot radius in CSS pixels at the fitted zoom, by listeners (log scale) */
  radius: Float32Array;
  /** indexes, most-listened first: covers and titles go to these first */
  byListeners: Int32Array;
  indexOf: Map<string, number>;
  genres: { name: string; albums: number[] }[];
  labels: AlbumMapData["labels"];
  /** bucket b holds cellItems[cellStart[b] .. cellStart[b + 1]] */
  cellStart: Int32Array;
  cellItems: Int32Array;
  search: string[];
}

const bucket = (x: number, y: number) =>
  Math.min(SIDE - 1, Math.max(0, Math.floor(y / CELL))) * SIDE + Math.min(SIDE - 1, Math.max(0, Math.floor(x / CELL)));

export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

export function buildModel(data: AlbumMapData): MapModel {
  const a = data.albums;
  const n = a.id.length;
  const xs = Float32Array.from(a.x), ys = Float32Array.from(a.y);
  const logs = a.listeners.map((l) => Math.log(Math.max(1, l)));
  const lo = Math.min(...logs), hi = Math.max(...logs);
  const radius = Float32Array.from(logs, (l) => 1.3 + 2.4 * ((l - lo) / (hi - lo || 1)));
  const byListeners = Int32Array.from([...Array(n).keys()].sort((i, j) => a.listeners[j] - a.listeners[i]));
  const counts = new Int32Array(SIDE * SIDE + 1);
  for (let i = 0; i < n; i++) counts[bucket(xs[i], ys[i]) + 1]++;
  for (let b = 1; b < counts.length; b++) counts[b] += counts[b - 1];
  const cellStart = counts.slice();
  const fill = counts.slice();
  const cellItems = new Int32Array(n);
  for (let i = 0; i < n; i++) cellItems[fill[bucket(xs[i], ys[i])]++] = i;
  return {
    n, ids: a.id, titles: a.title, artists: a.artist, years: a.year, listeners: a.listeners, xs, ys, radius, byListeners,
    indexOf: new Map(a.id.map((id, i) => [id, i])), genres: data.genres.map(({ name, steps }) => {
      let at = -1;
      return { name, albums: steps.map((step) => (at += step)) };
    }), labels: data.labels, cellStart, cellItems,
    search: a.id.map((_, i) => `${fold(a.title[i])} | ${fold(a.artist[i])}`),
  };
}

/** The album nearest (x, y) within `within` map units, or null. */
export function nearest(m: MapModel, x: number, y: number, within: number, only?: (i: number) => boolean): number | null {
  let best: number | null = null, bestD = within * within;
  const c0 = Math.max(0, Math.floor((x - within) / CELL)), c1 = Math.min(SIDE - 1, Math.floor((x + within) / CELL));
  const r0 = Math.max(0, Math.floor((y - within) / CELL)), r1 = Math.min(SIDE - 1, Math.floor((y + within) / CELL));
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const b = r * SIDE + c;
      for (let k = m.cellStart[b]; k < m.cellStart[b + 1]; k++) {
        const i = m.cellItems[k];
        if (only && !only(i)) continue;
        const d = (m.xs[i] - x) ** 2 + (m.ys[i] - y) ** 2;
        if (d <= bestD) { bestD = d; best = i; }
      }
    }
  }
  return best;
}

/** Albums whose title or artist words start with every typed word; title matches first, then most listened. */
export function findOnMap(m: MapModel, q: string, limit = 8): number[] {
  const words = fold(q).split(" ").filter(Boolean);
  if (!words.length) return [];
  const hits: [number, number][] = [];
  for (let i = 0; i < m.n; i++) {
    const s = m.search[i];
    if (words.every((w) => s.startsWith(w) || s.includes(` ${w}`))) {
      const titleFirst = s.startsWith(words[0]) ? 0 : 1;
      hits.push([titleFirst, i]);
    }
  }
  hits.sort((p, q2) => p[0] - q2[0] || m.listeners[q2[1]] - m.listeners[p[1]]);
  return hits.slice(0, limit).map(([, i]) => i);
}

export function albumAt(m: MapModel, i: number): Album {
  return { id: m.ids[i], title: m.titles[i], artist: m.artists[i], year: m.years[i], genres: [], coverUrl: `/api/covers/${m.ids[i]}` };
}
