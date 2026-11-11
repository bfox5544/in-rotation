/** Site themes (ADR 0027). Charcoal is the default; the others set data-theme on <html>, which swaps the color
 *  tokens at the top of styles.css. The choice is saved per browser, like the For You depth. index.html applies it
 *  before the page first draws, so there's no flash of the default colors. */
export const THEME_KEY = "inrotation.theme";

export interface Theme {
  key: "charcoal" | "gallery" | "midnight";
  label: string;
  hint: string;
  /** Page, panel, text, action color, save color: the picker's swatch strip. */
  swatches: string[];
}

export const THEMES: Theme[] = [
  { key: "charcoal", label: "Charcoal", hint: "Dark gray with amber. The original look.",
    swatches: ["#1f2022", "#2a2c2f", "#ececec", "#f2b84b", "#4cd0c4"] },
  { key: "gallery", label: "Gallery", hint: "Light, with cobalt blue. Easiest to read in daylight.",
    swatches: ["#f7f8f9", "#eceef1", "#16181b", "#2346d6", "#0d8577"] },
  { key: "midnight", label: "Midnight", hint: "Deep blue-black, with coral.",
    swatches: ["#0f1422", "#171e31", "#e7ebf5", "#ff8a66", "#a6b2ff"] },
];

export type ThemeKey = Theme["key"];

export function storedTheme(): ThemeKey {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return THEMES.some((t) => t.key === v) ? (v as ThemeKey) : "charcoal";
  } catch {
    return "charcoal";
  }
}

export function applyTheme(key: ThemeKey) {
  if (key === "charcoal") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", key);
  try {
    if (key === "charcoal") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, key);
  } catch {
    // Private windows can block storage; the theme then lasts for this visit only.
  }
}
