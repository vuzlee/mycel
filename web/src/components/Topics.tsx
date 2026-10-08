/** Where you are inside a long conversation. */

import { useEffect, useState } from "react";

export interface Topic {
  /** The id of the element this entry scrolls to — `anchorFor` writes the same string. */
  id: string;
  label: string;
}

export function anchorFor(jobId: string): string {
  return `turn-${jobId}`;
}

interface Props {
  topics: Topic[];
  /** The scrolling body the turns live in. The observer needs it as its root, and it
   *  arrives a render late, which is why this is state upstream rather than a ref. */
  root: HTMLElement | null;
}

export function Topics({ topics, root }: Props) {
  const [here, setHere] = useState<string | null>(null);

  useEffect(() => {
    if (!root || topics.length === 0) return;
    if (!("IntersectionObserver" in window)) return;

    const seen = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) seen.add(entry.target.id);
          else seen.delete(entry.target.id);
        }
        // The topmost turn still on screen, in the order they were asked. Two turns are
        // visible together often enough that "the last one to cross" reads as jitter.
        const first = topics.find((topic) => seen.has(topic.id));
        if (first) setHere(first.id);
      },
      // The band is the upper part of the body: a turn is "the one you are reading" when
      // its head is near the top, not when its tail is scrolling past the bottom.
      { root, rootMargin: "0px 0px -62% 0px" },
    );

    for (const topic of topics) {
      const node = document.getElementById(topic.id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, [root, topics]);

  if (topics.length < 2) return null;

  return (
    <nav className="topics" aria-label="Turns in this conversation">
      <ol>
        {topics.map((topic) => (
          <li key={topic.id}>
            <button
              aria-current={topic.id === here}
              title={topic.label}
              onClick={() =>
                document
                  .getElementById(topic.id)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              {topic.label}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
