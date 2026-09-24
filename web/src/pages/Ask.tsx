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

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Turn } from "../api";
import { askChat, fetchTurns } from "../api";
import { Answer } from "../components/Answer";
import type { ComposerHandle } from "../components/Composer";
import { Composer } from "../components/Composer";
import { PastTurns } from "../components/PastTurns";
import { Shell } from "../components/Shell";
import { Thread } from "../components/Thread";
import type { Topic } from "../components/Topics";
import { Topics, anchorFor } from "../components/Topics";
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
  // The scrolling body, as the observer in `Topics` needs it: a root, not a ref, because
  // it arrives one render after the first paint and the observer has to be rebuilt then.
  const [body, setBody] = useState<HTMLElement | null>(null);

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


  // Asking sends the view to the question just asked, and only then. One move per run, at
  // the moment there is a reason to move: the question goes to the top, the answer writes
  // itself into the room below it, and from then on the scroll is the reader's. Nothing
  // follows the text — a view that re-anchored on every token would be taking the page
  // back from whoever is reading it, dozens of times a run.
  //
  // The top rather than the bottom. The work happens below the question, so the top is
  // where the room is; sending it to the bottom would pin it to the last line and push it
  // off screen again at the first tool call.
  //
  // Layout effect, and after the earlier turns are in: they are what the new turn's offset
  // is measured from, and an effect that runs before they render scrolls to a position
  // that stops existing one frame later.
  const landed = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (jobId === null || question === null) return;
    if (landed.current === jobId) return;
    const node = document.getElementById(anchorFor(jobId));
    if (!node) return;
    landed.current = jobId;
    node.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [jobId, question, past]);

  // One entry per turn, the question as its own label. Trimmed rather than named by a
  // model: the question is already the name of the turn, and it costs nothing.
  // Memoised because `Topics` rebuilds its observer whenever the list changes, and a
  // fresh array every render would rebuild it on every streamed token.
  const topics: Topic[] = useMemo(
    () =>
      jobId === null
        ? []
        : [...past, ...(question !== null ? [{ job_id: jobId, question }] : [])].map((turn) => ({
            id: anchorFor(turn.job_id),
            label: label(turn.question),
          })),
    [jobId, past, question],
  );

  return (
    <Shell
      current={jobId}
      scrollRef={(node) => {
        run.follow.ref(node);
        setBody(node);
      }}
      aside={topics.length > 1 ? <Topics topics={topics} root={body} /> : undefined}
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
          anchor={anchorFor(jobId)}
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

/** A question is a sentence; a rail entry is a line. Cut on a word so the label never
 *  ends mid-word, and only when there is enough to be worth cutting. */
function label(question: string): string {
  const flat = question.replace(/\s+/g, " ").trim();
  if (flat.length <= 42) return flat;
  const cut = flat.slice(0, 42);
  const space = cut.lastIndexOf(" ");
  return `${space > 20 ? cut.slice(0, space) : cut}…`;
}
