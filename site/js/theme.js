// Light/dark theme: follows the device setting until the viewer picks one with the
// header toggle; the choice is saved in localStorage and applied on every page by a
// small inline snippet in <head> (so there's no flash of the wrong theme).
// Fires a "themechange" event on window so the map and charts can redraw.

const KEY = "theme";
const media = matchMedia("(prefers-color-scheme: dark)");

export function currentTheme() {
  return document.documentElement.dataset.theme || (media.matches ? "dark" : "light");
}

function apply(theme, save) {
  document.documentElement.dataset.theme = theme;
  if (save) {
    try { localStorage.setItem(KEY, theme); } catch { /* private mode: still works for this page */ }
  }
  updateButton();
  window.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
}

const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5M12 19.5V22M4.2 4.2l1.8 1.8M18 18l1.8 1.8M2 12h2.5M19.5 12H22M4.2 19.8 6 18M18 6l1.8-1.8"/></svg>`;
const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>`;

function updateButton() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const dark = currentTheme() === "dark";
  btn.innerHTML = dark ? SUN : MOON;
  btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  btn.setAttribute("aria-pressed", String(dark));
  btn.title = btn.getAttribute("aria-label");
}

export function mountThemeToggle() {
  const host = document.querySelector(".header-tools");
  if (!host || document.getElementById("theme-toggle")) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "theme-toggle";
  btn.className = "theme-toggle";
  btn.addEventListener("click", () => apply(currentTheme() === "dark" ? "light" : "dark", true));
  host.append(btn);
  updateButton();
}

// Follow the device setting live, unless the viewer has chosen a theme.
media.addEventListener("change", () => {
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch { /* ignore */ }
  if (!saved) {
    delete document.documentElement.dataset.theme;
    updateButton();
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: currentTheme() } }));
  }
});

mountThemeToggle();
