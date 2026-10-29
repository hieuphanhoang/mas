import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark";
const KEY = "mas.theme";

function read(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function system(): Theme {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Per-viewer convenience only (localStorage); the OS preference is the default. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => read() ?? system());
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage may be unavailable; theme still applies for this page */
      }
      return next;
    });
  }, []);
  return { theme, toggle };
}
