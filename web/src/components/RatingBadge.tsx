import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Album } from "../types";
import { Stars, formatStars } from "./Stars";
import { useLibrary } from "../state/library";

/** The badge on a cover: "★ 4½" when rated, "☆ Rate" when not. Either opens a star selector
 *  on the cover. It closes after a click on the stars, Enter, Escape, or a click elsewhere. */
export function RatingBadge({ album }: { album: Album }) {
  const { ratingOf } = useLibrary();
  const rating = ratingOf(album.id);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const badge = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    box.current?.querySelector<HTMLElement>('[role="slider"]')?.focus();
    const outside = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  const close = () => {
    setOpen(false);
    badge.current?.focus();
  };
  const escape = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };

  return (
    <div className="rating" ref={box} onKeyDown={escape}>
      <button ref={badge} type="button" className={rating === null ? "rating-badge unrated" : "rating-badge"}
        aria-haspopup="dialog" aria-expanded={open}
        aria-label={rating === null ? `Not rated. Rate ${album.title}` : `Your rating: ${rating} stars. Change rating of ${album.title}`}
        onClick={() => setOpen((o) => !o)}>
        {rating === null ? "☆ Rate" : `★ ${formatStars(rating)}`}
      </button>
      {open && (
        <div className="rating-pop" role="dialog" aria-label={`Rate ${album.title}`}>
          <Stars album={album} size={20} compact onDone={close} />
        </div>
      )}
    </div>
  );
}
