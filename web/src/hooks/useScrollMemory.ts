import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

/** Per-visit memory in sessionStorage (one tab, survives a reload), keyed by the history entry. */
const STORE = "inrotation.visits";
const KEEP = 60;   // history entries remembered

type Visits = Record<string, Record<string, unknown>>;
function read(): Visits {
  try {
    return JSON.parse(sessionStorage.getItem(STORE) ?? "{}") as Visits;
  } catch {
    return {};
  }
}
function write(v: Visits) {
  try {
    const keys = Object.keys(v);
    for (const k of keys.slice(0, Math.max(0, keys.length - KEEP))) delete v[k];
    sessionStorage.setItem(STORE, JSON.stringify(v));
  } catch {
    // Storage can be blocked (private windows); Back then starts at the top.
  }
}

/** Remember a value for this history entry (e.g. how many "Show More" pages were loaded). */
export function remember(entry: string, name: string, value: unknown) {
  const v = read();
  const entryValues = v[entry] ?? {};
  delete v[entry];                      // re-insert so recently used entries are kept longest
  v[entry] = { ...entryValues, [name]: value };
  write(v);
}
export function recall<T>(entry: string, name: string): T | undefined {
  return read()[entry]?.[name] as T | undefined;
}

const RESTORE_MS = 4000;   // wait this long for the page's data to make it tall enough
const SETTLE_MS = 600;     // then hold the position until the height stops changing this long

/** Back and Forward return to where you were on that page; opening a new page starts at the top.
 *  Changes that only touch the query string (filters, For You pages) leave the scroll alone. */
export function useScrollMemory() {
  const location = useLocation();
  const navType = useNavigationType();
  const entry = useRef(location.key);
  const path = useRef(location.pathname);

  useEffect(() => {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    let frame = 0;
    const save = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => remember(entry.current, "y", Math.round(window.scrollY)));
    };
    window.addEventListener("scroll", save, { passive: true });
    return () => {
      window.removeEventListener("scroll", save);
      cancelAnimationFrame(frame);
    };
  }, []);

  useLayoutEffect(() => {
    entry.current = location.key;
    const samePage = path.current === location.pathname;
    path.current = location.pathname;
    if (navType !== "POP") {
      if (!samePage) window.scrollTo(0, 0);
      return;
    }
    const y = recall<number>(location.key, "y") ?? 0;
    // Data loads after the page renders, and sections above (Picked for You, covers) can change
    // height after that. Keep putting the page back at `y` until its height has been steady for
    // SETTLE_MS, the reader scrolls on their own, or time runs out.
    let stopped = false;
    const stop = () => { stopped = true; };
    const started = performance.now();
    let height = -1, steadySince = started;
    const attempt = () => {
      if (stopped) return;
      const now = performance.now();
      const h = document.documentElement.scrollHeight;
      if (h !== height) { height = h; steadySince = now; }
      const room = h - window.innerHeight;
      if (room >= y || now - started > RESTORE_MS) {
        if (Math.round(window.scrollY) !== Math.min(y, Math.max(0, room))) window.scrollTo(0, Math.min(y, Math.max(0, room)));
        if (now - steadySince > SETTLE_MS || now - started > RESTORE_MS) return;
      }
      requestAnimationFrame(attempt);
    };
    attempt();
    const opts = { passive: true, once: true } as const;
    window.addEventListener("wheel", stop, opts);
    window.addEventListener("touchstart", stop, opts);
    window.addEventListener("keydown", stop, opts);
    return () => {
      stop();
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchstart", stop);
      window.removeEventListener("keydown", stop);
    };
  }, [location.key]);   // eslint-disable-line react-hooks/exhaustive-deps
}
