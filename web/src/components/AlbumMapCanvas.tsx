import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent } from "react";
import { WORLD, nearest, type MapModel } from "../lib/albumMap";
import { countryName } from "../lib/filters";
import { titleCase } from "../lib/text";

/** Where the map is looking: centre in map units, zoom relative to "whole map fits". */
export interface MapView { cx: number; cy: number; z: number }
export interface MapHandle {
  flyTo: (i: number, z?: number) => void;
  fit: (indexes: number[]) => void;
  zoomBy: (factor: number) => void;
  reset: () => void;
}
interface Props {
  model: MapModel;
  rated: Map<number, number>;          // map index -> your stars
  picks: Map<number, number>;          // map index -> For You rank (0 = best)
  highlight: Set<number> | null;       // a genre's albums
  showRated: boolean;
  showPicks: boolean;
  selected: number | null;
  onSelect: (i: number | null) => void;
  initialView?: MapView;
  onViewChange?: (v: MapView) => void;
  label: string;
}

// Colours come from the site tokens (styles.css), read once so the canvas matches the theme.
const css = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

const MIN_Z = 0.8, MAX_Z = 80;
const COVER_Z = 7;                     // covers replace dots from this zoom
const TIER_Z = [0, 2, 4];              // region label tiers appear from these zooms
const MAX_COVERS = 260;                // covers drawn per frame at most (most-listened first)
const MAX_LOADING = 24;                // cover images requested at once
const HIT_PX = { mouse: 12, touch: 22 };
const FIT_PAD = 0.94;
const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** The Album Map's canvas: drag to pan, wheel or pinch to zoom, click or tap to select (ADR 0022). */
export const AlbumMapCanvas = forwardRef<MapHandle, Props>(function AlbumMapCanvas(props, ref) {
  const { model, initialView } = props;
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<MapView>(initialView ?? { cx: WORLD / 2, cy: WORLD / 2, z: 1 });
  const size = useRef({ w: 0, h: 0, dpr: 1, fit: 1 });
  const latest = useRef(props);
  latest.current = props;
  const frame = useRef(0);
  const images = useRef(new Map<string, HTMLImageElement | null>());
  const pending = useRef(new Set<string>());
  const anim = useRef(0);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const hoverRef = useRef<number | null>(null);
  hoverRef.current = hover?.i ?? null;
  const colors = useRef<Record<string, string>>({});

  const scale = () => size.current.fit * view.current.z;
  const toScreen = (x: number, y: number): [number, number] => {
    const s = scale(), v = view.current;
    return [(x - v.cx) * s + size.current.w / 2, (y - v.cy) * s + size.current.h / 2];
  };
  const toWorld = (sx: number, sy: number): [number, number] => {
    const s = scale(), v = view.current;
    return [(sx - size.current.w / 2) / s + v.cx, (sy - size.current.h / 2) / s + v.cy];
  };

  const redraw = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      draw();
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changed = () => {
    redraw();
    latest.current.onViewChange?.({ ...view.current });
  };
  const clamp = (v: MapView): MapView => ({
    z: Math.min(MAX_Z, Math.max(MIN_Z, v.z)),
    cx: Math.min(WORLD * 1.1, Math.max(-WORLD * 0.1, v.cx)),
    cy: Math.min(WORLD * 1.1, Math.max(-WORLD * 0.1, v.cy)),
  });
  const setView = (v: MapView) => { view.current = clamp(v); changed(); };

  const animateTo = (target: MapView) => {
    cancelAnimationFrame(anim.current);
    const to = clamp(target);
    if (reduceMotion()) { setView(to); return; }
    const from = { ...view.current }, start = performance.now(), ms = 650;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      const z = Math.exp(Math.log(from.z) + (Math.log(to.z) - Math.log(from.z)) * e);
      setView({ cx: from.cx + (to.cx - from.cx) * e, cy: from.cy + (to.cy - from.cy) * e, z });
      if (t < 1) anim.current = requestAnimationFrame(step);
    };
    anim.current = requestAnimationFrame(step);
  };
  const zoomAt = (sx: number, sy: number, factor: number, animated = false) => {
    const [wx, wy] = toWorld(sx, sy);
    const z = Math.min(MAX_Z, Math.max(MIN_Z, view.current.z * factor));
    const s = size.current.fit * z;
    const target = { z, cx: wx - (sx - size.current.w / 2) / s, cy: wy - (sy - size.current.h / 2) / s };
    if (animated) animateTo(target); else { cancelAnimationFrame(anim.current); setView(target); }
  };

  useImperativeHandle(ref, () => ({
    flyTo: (i, z = 12) => animateTo({ cx: model.xs[i], cy: model.ys[i], z: Math.max(view.current.z, z) }),
    fit: (indexes) => {
      if (!indexes.length) return;
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const i of indexes) {
        x0 = Math.min(x0, model.xs[i]); x1 = Math.max(x1, model.xs[i]);
        y0 = Math.min(y0, model.ys[i]); y1 = Math.max(y1, model.ys[i]);
      }
      const span = Math.max(x1 - x0, y1 - y0, 40) / FIT_PAD;
      const { w, h } = size.current;
      animateTo({ cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, z: (Math.min(w, h) / span) / size.current.fit * 0.85 });
    },
    zoomBy: (f) => zoomAt(size.current.w / 2, size.current.h / 2, f, true),
    reset: () => animateTo({ cx: WORLD / 2, cy: WORLD / 2, z: 1 }),
  }));

  /** A cover image: the image, null when there's no art, undefined while it loads (or waits its turn). */
  function image(id: string): HTMLImageElement | null | undefined {
    if (images.current.has(id)) return images.current.get(id);
    if (pending.current.has(id) || pending.current.size >= MAX_LOADING) return undefined;
    pending.current.add(id);
    const img = new Image();
    img.decoding = "async";
    const done = (ok: boolean) => { pending.current.delete(id); images.current.set(id, ok ? img : null); redraw(); };
    img.onload = () => done(true);
    img.onerror = () => done(false);
    img.src = `/api/covers/${id}`;
    return undefined;
  }

  function draw() {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const p = latest.current, m = p.model, col = colors.current;
    const { w, h, dpr } = size.current;
    const z = view.current.z;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = col.bg;
    ctx.fillRect(0, 0, w, h);
    const grow = 1 + 0.35 * Math.log2(Math.max(1, z));
    const [wx0, wy0] = toWorld(-40, -40), [wx1, wy1] = toWorld(w + 40, h + 40);
    const visible: number[] = [];
    for (let i = 0; i < m.n; i++) {
      const x = m.xs[i], y = m.ys[i];
      if (x >= wx0 && x <= wx1 && y >= wy0 && y <= wy1) visible.push(i);
    }
    const coverMode = z >= COVER_Z;
    const coverPx = Math.min(84, 3.6 * z);

    // Covers first decide which albums show as art, so their dots aren't drawn underneath.
    const covered = new Map<number, [number, number]>();
    if (coverMode) {
      const taken: [number, number][] = [];
      const isVisible = new Set(visible);
      // The selected album first, then yours, then the most listened.
      const first = [p.selected, ...(p.showRated ? p.rated.keys() : [])].filter((i): i is number => i !== null);
      const order = function* () { yield* first; yield* m.byListeners; };
      const seen = new Set<number>();
      for (const i of order()) {
        if (covered.size >= MAX_COVERS) break;
        if (seen.has(i) || !isVisible.has(i)) continue;
        seen.add(i);
        const [sx, sy] = toScreen(m.xs[i], m.ys[i]);
        if (taken.some(([tx, ty]) => Math.abs(tx - sx) < coverPx + 2 && Math.abs(ty - sy) < coverPx + 2)) continue;
        const img = image(m.ids[i]);
        if (img === null) continue;                  // no art archived: stays a dot
        taken.push([sx, sy]);
        covered.set(i, [sx, sy]);
      }
    }

    // Dots, batched by colour. A highlighted genre turns its albums light and dims the rest.
    const hl = p.highlight;
    const groups: [string, number[]][] = hl
      ? [[col.dim, visible.filter((i) => !hl.has(i))], [col.text, visible.filter((i) => hl.has(i))]]
      : [[col.dot, visible]];
    for (const [fill, items] of groups) {
      ctx.fillStyle = fill;
      ctx.beginPath();
      for (const i of items) {
        if (covered.has(i)) continue;
        const [sx, sy] = toScreen(m.xs[i], m.ys[i]);
        const r = m.radius[i] * grow;
        ctx.moveTo(sx + r, sy);
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
      }
      ctx.fill();
    }

    // Your marks on dots: For You picks as teal rings, rated albums as amber dots (shape and colour both differ).
    const ring = (i: number) => m.radius[i] * grow;
    if (p.showPicks) {
      ctx.lineWidth = 1.5;
      for (const i of visible) {
        if (!p.picks.has(i) || covered.has(i) || (p.showRated && p.rated.has(i))) continue;
        const [sx, sy] = toScreen(m.xs[i], m.ys[i]);
        ctx.beginPath();
        ctx.arc(sx, sy, ring(i) + 3.5, 0, Math.PI * 2);
        ctx.strokeStyle = col.bg; ctx.lineWidth = 4; ctx.stroke();
        ctx.strokeStyle = col.teal; ctx.lineWidth = 1.75; ctx.stroke();
      }
    }
    if (p.showRated) {
      for (const i of visible) {
        if (!p.rated.has(i) || covered.has(i)) continue;
        const [sx, sy] = toScreen(m.xs[i], m.ys[i]);
        ctx.beginPath();
        ctx.arc(sx, sy, ring(i) + 2, 0, Math.PI * 2);
        ctx.fillStyle = col.amber; ctx.strokeStyle = col.bg; ctx.lineWidth = 2;
        ctx.fill(); ctx.stroke();
      }
    }

    // Covers on top, so marks on uncovered neighbours never sit across the art. Your marks show as a 2px outline.
    const half = coverPx / 2;
    for (const [i, [sx, sy]] of covered) {
      const img = images.current.get(m.ids[i]);
      const dimmed = hl && !hl.has(i);
      ctx.globalAlpha = dimmed ? 0.25 : 1;
      if (img) ctx.drawImage(img, sx - half, sy - half, coverPx, coverPx);
      else { ctx.fillStyle = col.raised; ctx.fillRect(sx - half, sy - half, coverPx, coverPx); }
      ctx.globalAlpha = 1;
      const mark = p.showRated && p.rated.has(i) ? col.amber : p.showPicks && p.picks.has(i) ? col.teal : null;
      if (mark) {
        ctx.strokeStyle = mark;
        ctx.lineWidth = 2;
        ctx.strokeRect(sx - half - 2, sy - half - 2, coverPx + 4, coverPx + 4);
      }
    }

    // Selection and hover rings.
    for (const [i, colour] of [[p.selected, col.text], [hoverRef.current, col.soft]] as [number | null, string][]) {
      if (i === null) continue;
      const at = covered.get(i);
      ctx.strokeStyle = colour; ctx.lineWidth = 2;
      if (at) ctx.strokeRect(at[0] - half - 4, at[1] - half - 4, coverPx + 8, coverPx + 8);
      else {
        const [sx, sy] = toScreen(m.xs[i], m.ys[i]);
        ctx.beginPath(); ctx.arc(sx, sy, ring(i) + 6, 0, Math.PI * 2); ctx.stroke();
      }
    }

    const boxes: [number, number, number, number][] = [];
    const free = (x0: number, y0: number, x1: number, y1: number) =>
      x0 >= 0 && x1 <= w && y0 >= 0 && y1 <= h && !boxes.some(([a, b, c2, d]) => x0 < c2 && x1 > a && y0 < d && y1 > b);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";

    // Album titles under the bigger covers.
    if (coverMode && coverPx >= 46) {
      ctx.font = `500 11px ${col.sans}`;
      for (const [i, [sx, sy]] of covered) {
        const text = fitText(ctx, m.titles[i], coverPx + 24);
        const tw = ctx.measureText(text).width, ty = sy + half + 10;
        if (!free(sx - tw / 2 - 2, ty - 7, sx + tw / 2 + 2, ty + 7)) continue;
        boxes.push([sx - tw / 2 - 2, ty - 7, sx + tw / 2 + 2, ty + 7]);
        ctx.strokeStyle = col.bg; ctx.lineWidth = 3; ctx.strokeText(text, sx, ty);
        ctx.fillStyle = col.soft; ctx.fillText(text, sx, ty);
      }
    }

    // Region labels (genres and countries) while zoomed out; tier by tier, skipping any that would collide.
    if (!coverMode) {
      for (const lab of m.labels) {
        if (z < TIER_Z[lab.tier]) continue;
        const [sx, sy] = toScreen(lab.x, lab.y);
        const text = lab.kind === "country" ? countryName(lab.name) : titleCase(lab.name);
        const top = lab.tier === 0;
        ctx.font = top ? `700 12px ${col.sans}` : `600 11.5px ${col.sans}`;
        (ctx as CanvasRenderingContext2D & { letterSpacing?: string }).letterSpacing = top ? "0.08em" : "0px";
        const shown = top ? text.toUpperCase() : text;
        const tw = ctx.measureText(shown).width;
        if (!free(sx - tw / 2 - 4, sy - 9, sx + tw / 2 + 4, sy + 9)) continue;
        boxes.push([sx - tw / 2 - 4, sy - 9, sx + tw / 2 + 4, sy + 9]);
        ctx.strokeStyle = col.bg; ctx.lineWidth = 4; ctx.strokeText(shown, sx, sy);
        ctx.fillStyle = top ? col.text : col.soft; ctx.fillText(shown, sx, sy);
      }
      (ctx as CanvasRenderingContext2D & { letterSpacing?: string }).letterSpacing = "0px";
    }
  }

  // Size, colours and fonts.
  useEffect(() => {
    colors.current = {
      bg: css("--bg", "#1f2022"), raised: css("--raised", "#36393d"), text: css("--text", "#ececec"),
      soft: css("--text-soft", "#a9aeb5"), amber: css("--amber", "#f2b84b"), teal: css("--teal", "#4cd0c4"),
      dot: css("--map-dot", "#73777e"), dim: css("--map-dim", "#3b3e43"), sans: css("--sans", "system-ui, sans-serif"),
    };
    const el = wrap.current, c = canvas.current;
    if (!el || !c) return;
    const resize = () => {
      const { width, height } = el.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      size.current = { w: width, h: height, dpr, fit: (Math.min(width, height) / WORLD) * FIT_PAD };
      c.width = Math.round(width * dpr);
      c.height = Math.round(height * dpr);
      c.style.width = `${width}px`;
      c.style.height = `${height}px`;
      draw();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    document.fonts?.ready.then(redraw).catch(() => undefined);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame.current);
      frame.current = 0;                  // or the next redraw() would think a frame is still pending
      cancelAnimationFrame(anim.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(redraw, [props.rated, props.picks, props.highlight, props.showRated, props.showPicks, props.selected, hover, redraw]);

  // Pointers: one drags, two pinch; a press that barely moves is a click.
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const pointers = new Map<number, { x: number; y: number }>();
    let drag: { x: number; y: number; cx: number; cy: number; moved: boolean } | null = null;
    let pinch: { d: number; z: number; wx: number; wy: number } | null = null;
    const local = (e: PointerEvent | WheelEvent | MouseEvent) => {
      const r = c.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const pick = (x: number, y: number, touch: boolean) => {
      const [wx, wy] = toWorld(x, y);
      const within = (touch ? HIT_PX.touch : HIT_PX.mouse) / scale();
      const covered = view.current.z >= COVER_Z ? Math.min(84, 3.6 * view.current.z) / 2 / scale() : 0;
      return nearest(latest.current.model, wx, wy, Math.max(within, covered * 1.2));
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      c.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, local(e));
      cancelAnimationFrame(anim.current);
      if (pointers.size === 1) {
        const p = local(e);
        drag = { ...p, cx: view.current.cx, cy: view.current.cy, moved: false };
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const [wx, wy] = toWorld((a.x + b.x) / 2, (a.y + b.y) / 2);
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, z: view.current.z, wx, wy };
        if (drag) drag.moved = true;
      }
    };
    const move = (e: PointerEvent) => {
      const p = local(e);
      if (!pointers.has(e.pointerId)) {
        if (e.pointerType === "mouse") {
          const i = pick(p.x, p.y, false);
          setHover(i === null ? null : { i, x: p.x, y: p.y });
          c.style.cursor = i === null ? "grab" : "pointer";
        }
        return;
      }
      pointers.set(e.pointerId, p);
      if (pinch && pointers.size >= 2) {
        const [a, b] = [...pointers.values()];
        const z = Math.min(MAX_Z, Math.max(MIN_Z, pinch.z * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d));
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, s = size.current.fit * z;
        setView({ z, cx: pinch.wx - (mx - size.current.w / 2) / s, cy: pinch.wy - (my - size.current.h / 2) / s });
      } else if (drag) {
        const dx = p.x - drag.x, dy = p.y - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > 4) { drag.moved = true; setHover(null); c.style.cursor = "grabbing"; }
        if (drag.moved) setView({ ...view.current, cx: drag.cx - dx / scale(), cy: drag.cy - dy / scale() });
      }
    };
    const up = (e: PointerEvent) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 0) {
        if (drag && !drag.moved && e.type === "pointerup") {
          const p = local(e);
          latest.current.onSelect(pick(p.x, p.y, e.pointerType !== "mouse"));
        }
        drag = null;
        c.style.cursor = "grab";
      } else if (pointers.size === 1) {
        const [only] = [...pointers.values()];
        drag = { ...only, cx: view.current.cx, cy: view.current.cy, moved: true };
      }
    };
    const leave = () => setHover(null);
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = local(e);
      const unit = e.deltaMode === 1 ? 16 : 1;
      zoomAt(p.x, p.y, Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0018)));
    };
    const dbl = (e: MouseEvent) => { const p = local(e); zoomAt(p.x, p.y, e.shiftKey ? 0.5 : 2, true); };
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("pointerleave", leave);
    c.addEventListener("wheel", wheel, { passive: false });
    c.addEventListener("dblclick", dbl);
    return () => {
      c.removeEventListener("pointerdown", down);
      c.removeEventListener("pointermove", move);
      c.removeEventListener("pointerup", up);
      c.removeEventListener("pointercancel", up);
      c.removeEventListener("pointerleave", leave);
      c.removeEventListener("wheel", wheel);
      c.removeEventListener("dblclick", dbl);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const keys = (e: KeyboardEvent) => {
    const step = 80 / scale();
    const v = view.current;
    const moves: Record<string, () => void> = {
      ArrowLeft: () => setView({ ...v, cx: v.cx - step }), ArrowRight: () => setView({ ...v, cx: v.cx + step }),
      ArrowUp: () => setView({ ...v, cy: v.cy - step }), ArrowDown: () => setView({ ...v, cy: v.cy + step }),
      "+": () => zoomAt(size.current.w / 2, size.current.h / 2, 1.6, true), "=": () => zoomAt(size.current.w / 2, size.current.h / 2, 1.6, true),
      "-": () => zoomAt(size.current.w / 2, size.current.h / 2, 1 / 1.6, true), "0": () => animateTo({ cx: WORLD / 2, cy: WORLD / 2, z: 1 }),
      Escape: () => latest.current.onSelect(null),
    };
    const run = moves[e.key];
    if (run) { e.preventDefault(); run(); }
  };

  const m = model;
  const tip = hover && hover.i !== props.selected ? hover : null;
  return (
    <div className="map-canvas" ref={wrap}>
      <canvas ref={canvas} tabIndex={0} role="img" aria-label={props.label} onKeyDown={keys} />
      {tip && (
        <div className="map-tip" style={{ left: tip.x, top: tip.y }} aria-hidden="true">
          <strong>{m.titles[tip.i]}</strong>
          <span>{m.artists[tip.i]}{m.years[tip.i] ? `, ${m.years[tip.i]}` : ""}</span>
          {props.rated.has(tip.i) && <span className="map-tip-mark rated">You rated it {stars(props.rated.get(tip.i)!)}</span>}
          {!props.rated.has(tip.i) && props.picks.has(tip.i) && <span className="map-tip-mark pick">On your For You</span>}
        </div>
      )}
    </div>
  );
});

export const stars = (n: number) => `★ ${Math.floor(n) || ""}${n % 1 ? "½" : ""}`;

function fitText(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text;
  let lo = 0, hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(`${text.slice(0, mid).trimEnd()}…`).width <= max) lo = mid; else hi = mid - 1;
  }
  return `${text.slice(0, lo).trimEnd()}…`;
}
