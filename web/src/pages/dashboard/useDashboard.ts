import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Dashboard as Board } from "../../api";
import { Unauthorized, fetchDashboard, fetchProjects } from "../../api";
import { useAuth } from "../../context/auth";
import { WINDOWS } from "./format";

const EVERY_MS = 30_000;

/** Projects, the polled board, and the project/window kept in the URL. */
export function useDashboard() {
  const [params, setParams] = useSearchParams();
  const { forget } = useAuth();

  const [projects, setProjects] = useState<string[] | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const project = params.get("project");
  // A hand-edited `?days=` goes straight into a fetch, so off-menu values fall back.
  const asked = Number(params.get("days"));
  const window_ = WINDOWS.includes(asked) ? asked : 7;

  useEffect(() => {
    void fetchProjects()
      .then((found) => {
        setProjects(found);
        // The project lives in the URL so a board is a link someone can keep.
        if (project === null && found[0]) {
          setParams({ project: found[0], days: String(window_) }, { replace: true });
        }
      })
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) forget();
        else setProjects([]);
      });
    // Only on mount: re-picking a default every time the window changes would fight the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (project === null) return;
    let live = true;

    const load = (): void => {
      void fetchDashboard(project, window_)
        .then((found) => {
          if (!live) return;
          setBoard(found);
          setFailure(null);
        })
        .catch((error: unknown) => {
          if (!live) return;
          if (error instanceof Unauthorized) forget();
          else setFailure(error instanceof Error ? error.message : String(error));
        });
    };

    load();
    const timer = globalThis.setInterval(load, EVERY_MS);
    return () => {
      live = false;
      globalThis.clearInterval(timer);
    };
  }, [project, window_, forget]);

  const pick = (next: { project?: string; days?: number }): void =>
    setParams({
      project: next.project ?? project ?? "",
      days: String(next.days ?? window_),
    });

  return { projects, board, failure, project, window_, pick };
}
