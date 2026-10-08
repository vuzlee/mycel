import { useEffect, useLayoutEffect, useRef } from "react";
import { anchorFor } from "../components/Topics";

/** Refetch the sidebar once per finished run: the worker reorders it minutes after the fetch. */
export function useRefetchOnSettle(
  jobId: string | null,
  status: string | undefined,
  reload: () => void,
): void {
  const refetched = useRef<string | null>(null);
  useEffect(() => {
    if (jobId === null) return;
    if (status !== "done" && status !== "failed") return;
    if (refetched.current === jobId) return;
    refetched.current = jobId;
    reload();
  }, [jobId, status, reload]);
}

/** Scroll a new question to the top of the body, once per run, after the earlier turns render. */
export function useScrollToQuestion(
  body: HTMLElement | null,
  jobId: string | null,
  question: string | null,
  pastFor: string | null,
  gap: number,
): void {
  const landed = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (jobId === null || question === null || body === null) return;
    if (pastFor !== jobId) return;
    if (landed.current === jobId) return;
    const node = document.getElementById(anchorFor(jobId));
    if (!node) return;
    landed.current = jobId;
    // Not `scrollIntoView`: that scrolls the least it can, not to the top.
    body.scrollTo({
      top:
        body.scrollTop + node.getBoundingClientRect().top - body.getBoundingClientRect().top - gap,
      behavior: "smooth",
    });
  }, [jobId, question, pastFor, body, gap]);
}
