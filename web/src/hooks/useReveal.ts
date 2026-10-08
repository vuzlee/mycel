/** A section appears as it is reached, once. */

import { useLayoutEffect, useRef } from "react";

export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  // Layout, not effect: the starting offset is applied before the browser paints, so the
  // band never appears in place and then jumps back to be animated in.
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!("IntersectionObserver" in window)) return;

    node.dataset.shown = "false";

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          (entry.target as HTMLElement).dataset.shown = "true";
          observer.unobserve(entry.target);
        }
      },
      // Fires a little before the edge, so the motion is finishing as the reader arrives
      // rather than starting when they are already looking at it.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.15 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return ref;
}
