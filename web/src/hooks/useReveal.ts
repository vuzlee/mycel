/**
 * A section appears as it is reached, once.
 *
 * Observed rather than tied to scroll position: a scroll handler runs on every frame of
 * every scroll for the whole life of the page, and this needs to fire once per element.
 * The observer stops watching an element the moment it has fired.
 *
 * Nothing here is load-bearing. The element is visible with no JavaScript at all — the
 * class only removes a starting offset — so a failed observer costs the animation, never
 * the content.
 */

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
