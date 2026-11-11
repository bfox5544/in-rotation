import { useState, type KeyboardEvent, type MouseEvent } from "react";
import type { Album } from "../types";
import { useLibrary } from "../state/library";

/** "4.5" -> "4½" */
export const formatStars = (stars: number) => `${Math.floor(stars) || ""}${stars % 1 ? "½" : ""}`;

export function starLabel(stars: number): string {
  if (stars < 2) return "Not for Me";
  if (stars < 3) return "Didn't click";
  if (stars < 4) return "Liked It";
  if (stars < 5) return "Really Liked It";
  return "Loved It";
}

const STAR = "M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6L2.5 9.4l6.6-.8z";

/** Five stars, each split into halves (0.5 to 5). Read-only when `onRate` is absent. */
export function StarGlyphs({ value, size = 26 }: { value: number; size?: number }) {
  return (
    <span className="star-glyphs" aria-hidden="true">
      {[1, 2, 3, 4, 5].map((n) => {
        const fill = Math.max(0, Math.min(1, value - (n - 1)));   // 0, 0.5 or 1
        return (
          <span key={n} className="star-glyph" style={{ width: size, height: size }}>
            <svg viewBox="0 0 24 24" width={size} height={size}><path d={STAR} /></svg>
            <span className="star-fill" style={{ width: `${fill * 100}%` }}>
              <svg viewBox="0 0 24 24" width={size} height={size}><path d={STAR} /></svg>
            </span>
          </span>
        );
      })}
    </span>
  );
}

/** The user's rating of an album, editable with the mouse (left or right half of a star) or the
 *  keyboard (arrows step by half a star, Home/End, 1-5, Delete clears). Choosing the current
 *  rating again clears it. Below 3 stars keeps an album out of recommendations; from 3 up it
 *  steers them, more stars more strongly. */
export function Stars({ album, size = 26, compact = false, onDone }: {
  album: Album; size?: number; compact?: boolean;
  /** Called after a click on the stars or Enter, e.g. to close a popover. */
  onDone?: () => void;
}) {
  const { ratingOf, rate } = useLibrary();
  return (
    <StarInput value={ratingOf(album.id)} onChange={(stars) => rate(album, stars)} label={`Your rating of ${album.title}`}
      size={size} compact={compact} onDone={onDone} />
  );
}

/** The star slider on its own: `value` in, `onChange` out (null clears), for a rating that isn't saved at once. */
export function StarInput({ value: current, onChange, label, size = 26, compact = false, onDone, clearable = true }: {
  value: number | null; onChange: (stars: number | null) => void; label: string;
  size?: number; compact?: boolean; onDone?: () => void;
  /** false: choosing the current value again keeps it */
  clearable?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? current ?? 0;
  const rate = (stars: number | null) => { if (stars !== null || clearable) onChange(stars); };

  const at = (e: MouseEvent<HTMLSpanElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const star = Math.min(4, Math.floor(((e.clientX - box.left) / box.width) * 5));
    const half = (e.clientX - box.left) / box.width * 5 - star < 0.5 ? 0.5 : 1;
    return star + half;
  };
  const set = (stars: number | null) => {
    rate(stars === current ? null : stars);
    onDone?.();
  };
  const key = (e: KeyboardEvent) => {
    const now = current ?? 0;
    const next: Record<string, number | null> = {
      ArrowRight: Math.min(5, now + 0.5), ArrowUp: Math.min(5, now + 0.5),
      ArrowLeft: Math.max(0.5, now - 0.5), ArrowDown: Math.max(0.5, now - 0.5),
      Home: 0.5, End: 5, Delete: null, Backspace: null, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
    };
    if (e.key === "Enter" && onDone) {
      e.preventDefault();
      onDone();
      return;
    }
    if (!(e.key in next)) return;
    e.preventDefault();
    const stars = next[e.key];
    if (stars !== current) rate(stars);
  };

  return (
    <div className={compact ? "stars-row compact" : "stars-row"}>
      <span className="stars" role="slider" tabIndex={0} aria-label={label}
        aria-valuemin={0.5} aria-valuemax={5} aria-valuenow={current ?? undefined}
        aria-valuetext={current ? `${current} stars, ${starLabel(current)}` : "Not rated"}
        onMouseMove={(e) => setHover(at(e))} onMouseLeave={() => setHover(null)}
        onClick={(e) => set(at(e))} onKeyDown={key}>
        <StarGlyphs value={shown} size={size} />
      </span>
      {!compact && (
        <span className="stars-label" aria-hidden="true">
          {shown ? <><strong>{formatStars(shown)}</strong> {starLabel(shown)}</> : "Rate It"}
        </span>
      )}
    </div>
  );
}
