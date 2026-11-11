// Minor words stay lowercase inside a title ("Under the Radar"); acronyms stay uppercase ("UK Garage").
const MINOR = new Set(["a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "vs", "with"]);
const ACRONYMS = new Set(["uk", "us", "usa", "idm", "edm", "ebm", "dj", "mpb", "aor", "nwobhm", "ost", "r&b", "rnb", "lo-fi"]);

/** Title case for names that arrive lowercase, such as MusicBrainz genres: "hip hop" -> "Hip Hop",
 *  "r&b" -> "R&B", "k-pop" -> "K-Pop", "music of the andes" -> "Music of the Andes". */
export function titleCase(text: string): string {
  return text.split(" ").map((word, i) => {
    const lower = word.toLowerCase();
    if (lower === "lo-fi") return "Lo-Fi";
    if (ACRONYMS.has(lower)) return lower.toUpperCase();
    if (i > 0 && MINOR.has(lower)) return lower;
    return lower.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("-");
  }).join(" ");
}
