import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchDashboard } from "../../api";
import { useProjects } from "../../lib/useProjects";
import { WINDOWS } from "./format";

const EVERY_MS = 30_000;

/** Projects, the polled board, and the project/window kept in the URL. */
export function useDashboard() {
  const [params, setParams] = useSearchParams();
  const project = params.get("project");
  // A hand-edited `?days=` goes straight into a fetch, so off-menu values fall back.
  const asked = Number(params.get("days"));
  const window_ = WINDOWS.includes(asked) ? asked : 7;

  const projectsQuery = useProjects();
  const projects = projectsQuery.data ?? (projectsQuery.isError ? [] : null);

  // The project lives in the URL so a board is a link someone can keep.
  useEffect(() => {
    if (project === null && projects?.[0]) {
      setParams({ project: projects[0], days: String(window_) }, { replace: true });
    }
    // Only when the list arrives: re-picking on every window change would fight the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  const boardQuery = useQuery({
    queryKey: ["dashboard", project, window_],
    queryFn: () => fetchDashboard(project as string, window_),
    enabled: project !== null,
    refetchInterval: EVERY_MS,
  });
  const board = boardQuery.data ?? null;
  const error = boardQuery.error;
  const failure = error && !boardQuery.data ? error.message : null;

  const pick = (next: { project?: string; days?: number }): void =>
    setParams({
      project: next.project ?? project ?? "",
      days: String(next.days ?? window_),
    });

  return { projects, board, failure, project, window_, pick };
}
