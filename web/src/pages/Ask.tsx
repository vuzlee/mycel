/**
 * Ask anything, and watch the run happen.
 *
 * The job id lives in the query string, not in state: a run is a thing you can link to
 * and reopen, and the sidebar reopens one by navigating rather than by lifting state up
 * through a router that is already carrying it.
 *
 * A thread is more than one turn since 031. `?thread=` rides beside `?job=`: the job is
 * the run being watched, the thread is what the next question joins. A reload with only
 * a job still works — the run itself names its thread.
 *
 * Which means a reload arrives with a job and no question — the question was only ever
 * in this component's state. The stream does not carry it either: a stream is tool calls
 * and reasoning, not the prompt that started them. So the poll carries both: since 032
 * `GET /chat/{id}` returns the run's own `question` and `conversation_id`, which the
 * sidebar cannot supply. A thread's title is the question that *opened* it, and its job
 * id is the *latest* run — both are the wrong answer from the second turn on.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Turn } from "../api";
import { askChat, fetchTurns } from "../api";
import { Answer } from "../components/Answer";
import type { ComposerHandle } from "../components/Composer";
import { Composer } from "../components/Composer";
import { PastTurns } from "../components/PastTurns";
import { Shell } from "../components/Shell";
import { Thread } from "../components/Thread";
import { ArrowRight } from "../components/icons";
import { useRun } from "../run";
import { useThreads } from "../threads";

// One per capability, because these buttons are the capability documentation people
// actually read — nobody opens the docs before typing a first question. Every screen the
// app still has its own page for is reachable from here too: progress is the summariser,
// the dashboard's numbers are the analyst writing its own SQL.
const SEEDS = [
  "How is MYC going this week?", // summariser — the progress summary
  "What is late right now, and who is it with?", // analyst — the dashboard's own question
  "Who logged the most hours this month, and on what?", // analyst, through run_sql
  "Compare hours logged this month with last month.", // analyst — two windows, one query
  "Anything important in my mail today?", // researcher — read_mail(24)
  "What came in this week that I have not replied to?", // researcher — read_mail(168)
  "What changed in the Jira API this year?", // researcher — the web
];

export function Ask() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const { reload } = useThreads();

  const [asked, setAsked] = useState<string | null>(null);
  const [past, setPast] = useState<Turn[]>([]);
  const [seed, setSeed] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const composer = useRef<ComposerHandle>(null);

  const run = useRun(jobId);

  // Arriving from the sidebar or a reloaded link: the question is not in this tab's
  // memory, and the stream does not carry it — a stream is tool calls, not the prompt.
  // The run itself says what it was asked, which the thread cannot: a thread's title is
  // the question that opened it, and captions every later turn wrongly.
  const question = asked ?? run.result?.question ?? null;

  // The thread the next question joins. `?thread=` first because it is there the moment
  // you navigate, while the run needs a poll to come back — and it is the run, not the
  // sidebar, that knows the thread of a link naming a turn other than the latest.
  const fromUrl = params.get("thread");
  const threadId = fromUrl ? Number(fromUrl) : (run.result?.conversation_id ?? null);

  // Everything this thread said before the run on screen. Turns are read from the kept
  // rows, not the stream: those runs are over, and a stream belongs to one run.
  useEffect(() => {
    if (threadId === null) {
      setPast([]);
      return;
    }
    let live = true;
    void fetchTurns(threadId)
      .then((turns) => {
        if (live) setPast(turns.filter((turn) => turn.job_id !== jobId));
      })
      .catch(() => {
        if (live) setPast([]);
      });
    return () => {
      live = false;
    };
  }, [threadId, jobId]);

  const startNew = useCallback(() => {
    setParams({}, { replace: false });
    setAsked(null);
    setPast([]);
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
      // The open thread by default, a new one only when the reader asked for one with
      // `+` or Cmd+K. Continuing is what every other conversation does; splitting is the
      // thing that takes a click.
      const { job_id, conversation_id } = await askChat(text, threadId ?? undefined);
      setAsked(text);
      setParams({ job: job_id, thread: String(conversation_id) });
      reload();
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  };

  const failure = refused ?? run.failure;

  return (
    <Shell
      current={jobId}
      scrollRef={run.follow.ref}
      jump={jobId !== null && run.follow.adrift ? run.follow.toBottom : undefined}
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
          before={past.length > 0 ? <PastTurns turns={past} /> : null}
          question={question}
          items={run.items}
          gaps={run.gaps}
          liveSeq={run.liveSeq}
          failure={failure}
          pending={run.pending}
        >
          {run.result?.status === "done" && (
            <Answer result={run.result} streamed={run.items.some((i) => i.kind === "text")} />
          )}
        </Thread>
      ) : (
        <div className="blank">
          <h1>
            Ask Mycel <em>anything</em>.
          </h1>
          <p>
            Your team's week, the numbers, your mail, or anything outside. Read-only
            &mdash; nothing you ask can change the work data.
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
