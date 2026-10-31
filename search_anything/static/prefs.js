"use strict";
/*
 * UI preferences. Loaded in <head> (before the page paints) so the chosen
 * theme/layout applies without a flash. Stored per browser in localStorage.
 *
 * Defaults show (almost) everything; users switch off what they don't want
 * in Settings, or pick the "minimal" preset.
 */
const PREFS_KEY = "sa-prefs";
// Bump when defaults change in a way that should replace values saved by an
// older version (v2: everything visible by default instead of minimal).
const PREFS_VERSION = 2;
const DEFAULT_PREFS = Object.freeze({
  // appearance
  theme: "system",        // system | light | dark
  accent: "auto",         // auto (black/white by theme) | #rrggbb
  fontSize: "md",         // sm | md | lg
  radius: "rounded",      // square | rounded | round
  density: "comfortable", // comfortable | compact
  font: "google",         // google | system
  motion: true,
  // what is shown
  layout: "framed",       // clean (single column) | framed (bordered panel)
  filters: "rail",        // hidden | tabs | rail
  detail: "side",         // drawer (opens on click) | side (always visible on wide screens)
  icons: "large",         // large | small | none
  snippets: true,         // text excerpt under results while searching
  recent: true,           // show recent items before typing
  footer: true,           // shortcuts + status bar
  vaultButton: true,      // lock/unlock button next to search
  scanIndicator: true,    // floating scan progress with a stop button
  // behaviour
  enterAction: "open",    // open (open file/link, copy password) | details
  resultLimit: 50,
});

// One-click presets (Settings → รีเซ็ต).
const PREF_PRESETS = Object.freeze({
  full: DEFAULT_PREFS,
  minimal: Object.freeze({
    ...DEFAULT_PREFS, layout: "clean", filters: "hidden", detail: "drawer", icons: "small",
    footer: false, vaultButton: false, scanIndicator: true,
  }),
});

function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    const prefs = { ...DEFAULT_PREFS };
    if ((saved.v || 1) < PREFS_VERSION) return prefs; // saved by an older version
    for (const key of Object.keys(DEFAULT_PREFS)) {
      if (key in saved && typeof saved[key] === typeof DEFAULT_PREFS[key]) prefs[key] = saved[key];
    }
    return prefs;
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function savePrefs(prefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify({ ...prefs, v: PREFS_VERSION })); } catch { /* private mode */ }
}

/** Readable text colour (black/white) for a background hex colour. */
function onColor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#171717" : "#fff";
}

function applyPrefs(prefs) {
  const root = document.documentElement;
  for (const key of ["theme", "fontSize", "radius", "density", "font", "layout", "filters", "detail", "icons"]) {
    root.dataset[key] = prefs[key];
  }
  for (const key of ["motion", "snippets", "recent", "footer", "vaultButton", "scanIndicator"]) {
    root.dataset[key] = prefs[key] ? "on" : "off";
  }
  // A side column only fits on wide screens; otherwise details open as a drawer.
  root.dataset.detailMode = prefs.detail === "side" && window.innerWidth > 900 ? "side" : "drawer";
  if (prefs.accent !== "auto" && /^#[0-9a-f]{6}$/i.test(prefs.accent)) {
    root.style.setProperty("--color-accent", prefs.accent);
    root.style.setProperty("--color-on-accent", onColor(prefs.accent));
    root.style.setProperty("--color-accent-muted", `color-mix(in srgb, ${prefs.accent} 14%, transparent)`);
  } else {
    root.style.removeProperty("--color-accent");
    root.style.removeProperty("--color-on-accent");
    root.style.removeProperty("--color-accent-muted");
  }
}

applyPrefs(loadPrefs());
