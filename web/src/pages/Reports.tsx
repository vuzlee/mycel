/**
 * A progress report: pick a project and a window, and an agent reads the work in it.
 *
 * No text box. Everything this run needs is a project key and a number of days — the
 * window goes into the prompt whole, so there is nothing for a person to phrase.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Unauthorized, askSummary, fetchProjects } from "../api";
import { CopyJobId, Elapsed } from "../components/RunMeta";
import { Shell, StatePill } from "../components/Shell";
import { Summary } from "../components/Summary";
import { Thread } from "../components/Thread";
import { Digest } from "../components/icons";
import { useAuth } from "../auth";
import { useRun } from "../run";
import { useThreads } from "../threads";

/** Offered windows. A standup looks back a day or a week; a month is a review. */
const WINDOWS = [1, 7, 14, 30];

export function Reports() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const { forget } = useAuth();
  const { reload } = useThreads();

  const [projects, setProjects] = useState<string[] | null>(null);
  const [project, setProject] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  /** What the run on screen covers, fixed when it was started. Reading the picker instead
   *  would relabel a finished report the moment somebody moves the selector. Null after a
   *  reload, where the summary's own `period` answers. */
  const [scope, setScope] = useState<string | null>(null);

  const run = useRun(jobId);

  useEffect(() => {
    void fetchProjects()
      .then((found) => {
        setProjects(found);
        setProject((current) => current ?? found[0] ?? null);
      })
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) forget();
        else setProjects([]);
      });
  }, [forget]);

  useEffect(() => {
    if (jobId) setStartedAt((at) => at ?? Date.now());
  }, [jobId]);

  const start = async (): Promise<void> => {
    if (project === null) return;
    setRefused(null);
    try {
      const { job_id } = await askSummary(project, days);
      setScope(`${project} · last ${days} days`);
      setStartedAt(Date.now());
      setParams({ job: job_id });
      reload();
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  };

  const summary = run.result?.status === "done" ? run.result.report : null;

  return (
    <Shell
      current={jobId}
      scrollRef={run.scrollRef}
      header={
        <>
          <StatePill state={refused ? "error" : run.state} />
          {startedAt !== null && <Elapsed since={startedAt} running={run.busy} />}
          {jobId && <CopyJobId jobId={jobId} />}
        </>
      }
    >
      <div className="page">
        <form
          className="picker"
          onSubmit={(event) => {
            event.preventDefault();
            void start();
          }}
        >
          <label>
            <span className="label">Project</span>
            <select
              value={project ?? ""}
              disabled={projects === null || projects.length === 0}
              onChange={(event) => setProject(event.target.value)}
            >
              {projects === null && <option>loading…</option>}
              {projects?.length === 0 && <option value="">no projects yet</option>}
              {projects?.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span className="label">Window</span>
            <div className="windows">
              {WINDOWS.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={option === days}
                  onClick={() => setDays(option)}
                >
                  {option}d
                </button>
              ))}
            </div>
          </label>

          <button className="primary" type="submit" disabled={project === null || run.busy}>
            <Digest />
            {run.busy ? "Running…" : "Run report"}
          </button>
        </form>

        {/* A project list that came back empty is not a broken page: nothing has synced
            yet, and saying so beats an empty dropdown that looks like a failure. */}
        {projects?.length === 0 && (
          <p className="note">
            Nothing has synced yet. Fill the Jira variables in <code>.env</code>, then run{" "}
            <code>scripts/stack.sh sync</code>.
          </p>
        )}

        {(refused ?? run.failure) && <p className="failure">{refused ?? run.failure}</p>}

        {/* The stream and the report are two different widths on purpose. Reasoning is
            prose and reads at a paragraph's width; the report is a seven-column table and
            reads at the page's. Nesting the second inside the first is what squeezed the
            tables into the middle third of a wide screen. */}
        {jobId && (
          <Thread
            question={null}
            items={run.items}
            gaps={run.gaps}
            liveSeq={run.liveSeq}
            failure={null}
            pending={run.pending}
          />
        )}

        {summary && (
          <Summary summary={summary} scope={scope} spent={run.result?.spent_usd} />
        )}
      </div>
    </Shell>
  );
}
