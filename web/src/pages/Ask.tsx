/**
 * Ask anything, and watch the run happen.
 *
 * The job id lives in the query string, not in state: a run is a thing you can link to
 * and reopen, and the sidebar reopens one by navigating rather than by lifting state up
 * through a router that is already carrying it.
 *
 * Which means a reload arrives with a job and no question — the question was only ever
 * in this component's state. The stream does not carry it either: a stream is tool calls
 * and reasoning, not the prompt that started them. But the sidebar has already fetched
 * every thread, and a thread's title *is* the question, so the reload reads it from
 * there. One less endpoint than asking the server for a string it already sent.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { askReport } from "../api";
import { Answer } from "../components/Answer";
import type { ComposerHandle } from "../components/Composer";
import { Composer } from "../components/Composer";
import { CopyJobId, Elapsed } from "../components/RunMeta";
import { Shell, StatePill } from "../components/Shell";
import { Thread } from "../components/Thread";
import { ArrowRight } from "../components/icons";
import { useRun } from "../run";
import { useThreads } from "../threads";

/* What the orchestrator can actually answer: questions it has to go and find out, and
   figures handed to it in the question itself. Not "what did my team ship" — that lives
   in gold, which these tools cannot reach, and the progress report is the page for it. */
// One per agent, because these buttons are the capability documentation people actually
// read — nobody opens the docs before typing a first question. Written when the analyst
// had no path to the data, they described a system that knew nothing about your project.
const SEEDS = [
  "How is MYC going this week?", // summariser
  "Who logged the most hours this month, and on what?", // analyst, through run_sql
  "What changed in the Jira API this year?", // researcher
];

export function Ask() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const { threads, reload } = useThreads();

  const [asked, setAsked] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const composer = useRef<ComposerHandle>(null);

  const run = useRun(jobId);

  // Arriving from the sidebar or a reloaded link: the question is not in this tab's
  // memory, and the stream does not carry it — a stream is tool calls, not the prompt.
  // The sidebar already holds it as the thread's title, so reuse that rather than add a
  // second endpoint returning the same string.
  const remembered = threads.find((t) => t.job_id === jobId)?.title ?? null;
  const question = asked ?? remembered;

  useEffect(() => {
    if (!jobId) return;
    setStartedAt((at) => at ?? Date.now());
  }, [jobId]);

  const startNew = useCallback(() => {
    setParams({}, { replace: false });
    setAsked(null);
    setStartedAt(null);
    setRefused(null);
    composer.current?.focus();
  }, [setParams]);

  // Cmd/Ctrl+K for a new run, the shortcut the button advertises.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        startNew();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [startNew]);

  const ask = async (text: string): Promise<void> => {
    setRefused(null);
    try {
      const { job_id } = await askReport(text);
      setAsked(text);
      setStartedAt(Date.now());
      setParams({ job: job_id });
      reload();
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  };

  const failure = refused ?? run.failure;

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
      footer={
        <Composer
          busy={run.busy}
          seed={seed}
          handle={composer}
          onAsk={(text) => void ask(text)}
        />
      }
    >
      {jobId ? (
        <Thread
          question={question}
          items={run.items}
          gaps={run.gaps}
          liveSeq={run.liveSeq}
          failure={failure}
          pending={run.pending}
        >
          {run.result?.status === "done" && <Answer result={run.result} />}
        </Thread>
      ) : (
        <div className="blank">
          <h1>
            Ask Mycel <em>anything</em>.
          </h1>
          <p>
            Your team's own week, the numbers behind it, or something outside this system
            entirely. Ask in plain language and watch the answer being put together. The
            work data is read-only, so nothing you ask can change it.
          </p>
          {refused && <p className="failure">{refused}</p>}
          <span className="label">Try one</span>
          <div className="seeds">
            {SEEDS.map((text) => (
              <button key={text} onClick={() => setSeed(text)}>
                {text}
                <ArrowRight />
              </button>
            ))}
          </div>
        </div>
      )}
    </Shell>
  );
}
