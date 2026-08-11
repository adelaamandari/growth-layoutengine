import { useEffect, useState } from "react";

// Theme state. Three modes, but only two themes: "auto" follows the OS
// and is the default, "light"/"dark" pin it.
//
// The RESOLVED theme is stamped on <html data-theme> — always, including
// when the mode is auto — so the stylesheet needs exactly one dark block
// keyed on that attribute instead of the same tokens written twice, once
// under a prefers-color-scheme query and once under the attribute. The
// inline script in index.html does the same stamp before first paint, so
// a dark user never gets a white flash while React boots.

const KEY = "linx-theme";

export const MODES = ["auto", "light", "dark"];

const systemDark = () =>
  window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

const read = () => {
  // localStorage throws in some privacy modes rather than returning
  // null, and a theme preference is not worth taking the app down for.
  try {
    const saved = localStorage.getItem(KEY);
    return MODES.includes(saved) ? saved : "auto";
  } catch {
    return "auto";
  }
};

export function useTheme() {
  const [mode, setMode] = useState(read);
  const [theme, setTheme] = useState(() =>
    document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"
  );

  useEffect(() => {
    const apply = () => {
      const dark = mode === "dark" || (mode === "auto" && systemDark());
      document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
      setTheme(dark ? "dark" : "light");
    };
    apply();

    try {
      if (mode === "auto") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch { /* see read() */ }

    // Only auto cares what the OS does; a pinned theme stays pinned.
    if (mode !== "auto") return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [mode]);

  return { mode, setMode, theme };
}
