import { useState } from "react";
import { applyTheme, storedTheme, THEMES, type ThemeKey } from "../lib/theme";

/** The site's color theme, under Account (ADR 0027). Applies at once and is remembered in this browser. */
export function ThemePicker() {
  const [theme, setTheme] = useState<ThemeKey>(storedTheme);
  const choose = (key: ThemeKey) => {
    setTheme(key);
    applyTheme(key);
  };
  return (
    <div className="account-theme">
      <h3 id="theme-heading">Theme</h3>
      <p className="muted">Changes how the site looks in this browser.</p>
      <div className="theme-options" role="radiogroup" aria-labelledby="theme-heading">
        {THEMES.map((t) => (
          <label key={t.key} className={t.key === theme ? "theme-option on" : "theme-option"}>
            <input type="radio" name="theme" value={t.key} checked={t.key === theme} onChange={() => choose(t.key)} />
            <span className="theme-swatches" aria-hidden="true">
              {t.swatches.map((c) => <span key={c} style={{ background: c }} />)}
            </span>
            <span className="theme-label">{t.label}</span>
            <span className="theme-hint">{t.hint}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
