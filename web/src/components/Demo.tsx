/**
 * The product, running, above the fold.
 *
 * A landing page can describe a thing or show it. This shows it: a question arrives, the
 * steps it takes appear in the order the real orchestrator would call them, and an answer
 * writes itself out. Then it holds, and moves to the next question.
 *
 * Scripted, not live. A real run needs an account, a Jira board and a model key, which is
 * three things a reader does not have yet — and it would cost a model request per visit.
 * The script is honest about shape: these are the real tool names behind `labelFor`, in
 * an order the orchestrator actually produces.
 *
 * The panel is a fixed height and the question is always whole. An earlier version typed
 * it a character at a time, which meant the first thing anyone saw was a window holding
 * the single letter H — a demo of a product is worth nothing if its first frame looks
 * broken. The motion is now in what the run *does*, which is the part worth watching.
 */

import { useEffect, useMemo, useState } from "react";
import { labelFor } from "../toolLabel";

interface Scene {
  question: string;
  steps: string[];
  answer: string;
  /** What the answer is built on. Three at most: a fourth is a table, and a table at
   *  this size is a thing nobody reads. */
  figures?: { label: string; value: string; bar: number; step: number }[];
}

const SCENES: Scene[] = [
  {
    question: "How is MYC going this week?",
    steps: ["summariser"],
    answer:
      "**On track.** Nine issues closed and two slipped a day. One to watch: MYC-21 is due Friday and has not started.",
    figures: [
      { label: "Closed", value: "9", bar: 100, step: 1 },
      { label: "In flight", value: "4", bar: 45, step: 2 },
      { label: "Late", value: "1", bar: 12, step: 4 },
    ],
  },
  {
    question: "Who logged the most hours this month?",
    steps: ["analyst", "run_sql", "percent_change"],
    answer:
      "**Ada, 47h** — 31h of it on MYC-17, then Grace at 38h. The team is up 12% on last month.",
    figures: [
      { label: "Ada", value: "47h", bar: 100, step: 1 },
      { label: "Grace", value: "38h", bar: 81, step: 2 },
      { label: "Alan", value: "29h", bar: 62, step: 3 },
    ],
  },
  {
    question: "Anything important in my mail today?",
    steps: ["researcher", "read_mail", "web_search"],
    answer:
      "**Two worth opening.** Atlassian is deprecating an endpoint you call, and your vendor has been waiting on you since Tuesday.",
  },
];

const STEP_MS = 700;
/** Between the last step and the first word: the pause a real run spends composing. */
const THINK_MS = 620;
/** Per word. Fast enough not to test anyone's patience, slow enough to read as written
 *  rather than pasted — which is the whole point of showing it arrive at all. */
const WORD_MS = 42;
/** How long a finished answer stays up. Long enough to read the figures twice, because
 *  the panel is the only place on the page that shows what the product returns. */
const HOLD_MS = 5200;
/** A beat of empty window between scenes. Without it the next question replaces the last
 *  answer in the same frame and the loop reads as a glitch rather than a new run. */
const CLEAR_MS = 520;

export function Demo() {
  const [scene, setScene] = useState(0);
  const [steps, setSteps] = useState(0);
  const [words, setWords] = useState(0);
  /** Between scenes: the window is cleared and nothing is being asked yet. */
  const [clearing, setClearing] = useState(false);
  const still = usePrefersStill();

  const current = SCENES[scene] ?? SCENES[0]!;
  const said = useMemo(() => tokenise(current.answer), [current.answer]);
  const working = steps < current.steps.length;
  const writing = !working && words < said.length;

  useEffect(() => {
    if (still) return;
    let timer = 0;

    if (clearing)
      timer = window.setTimeout(() => {
        setScene((n) => (n + 1) % SCENES.length);
        setSteps(0);
        setWords(0);
        setClearing(false);
      }, CLEAR_MS);
    else if (working) timer = window.setTimeout(() => setSteps((n) => n + 1), STEP_MS);
    else if (writing)
      timer = window.setTimeout(() => setWords((n) => n + 1), words === 0 ? THINK_MS : WORD_MS);
    else timer = window.setTimeout(() => setClearing(true), HOLD_MS);

    return () => window.clearTimeout(timer);
    // `steps` and `words` both belong here: the booleans above do not change between
    // one step and the next, so a dep list without the counters arms one timer and then
    // never arms another.
  }, [still, clearing, working, writing, steps, words]);

  // Standing still, the last frame is the whole frame: a reader who asked for no motion
  // still gets the thing the panel exists to show.
  const shown = still ? current.steps.length : steps;
  const written = still ? said.length : words;
  const answered = written >= said.length;

  return (
    <figure className="demo" aria-label="A question, and what Mycel returns">
      <div className="chrome">
        <span className="dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
        <span className="where">MYC</span>
        <span className="lamp" aria-hidden />
      </div>

      <div className="tape" key={scene} data-clearing={clearing}>
        <p className="asked">{current.question}</p>

        <div className="trace">
          {current.steps.map((tool, i) => (
            <p className="step" key={tool} data-state={i < shown ? "done" : i === shown ? "live" : "wait"}>
              <span className="pip" aria-hidden />
              {labelFor(tool)}
            </p>
          ))}
        </div>

        <div className="reply" data-shown={written > 0}>
          <p className="said" data-writing={!answered}>
            {said.slice(0, written).map((word, i) =>
              word.strong ? <b key={i}>{word.text} </b> : <span key={i}>{word.text} </span>,
            )}
          </p>
          {current.figures && (
            <ul className="figures">
              {current.figures.map((figure) => (
                <li key={figure.label} data-step={figure.step}>
                  <span className="name">{figure.label}</span>
                  <span className="track">
                    <span className="fill" style={{ width: answered ? `${figure.bar}%` : 0 }} />
                  </span>
                  <b>{figure.value}</b>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </figure>
  );
}

/**
 * One word, and whether it is bold.
 *
 * The markers are resolved up front, not at render: streaming a raw string a word at a
 * time would put `**On` on screen for 42ms, and a demo that flashes its own syntax is
 * worse than one that does not stream at all.
 */
interface Word {
  text: string;
  strong: boolean;
}

function tokenise(line: string): Word[] {
  return line.split(/(\*\*[^*]+\*\*)/).flatMap((part) => {
    const strong = part.startsWith("**");
    const body = strong ? part.slice(2, -2) : part;
    return body
      .split(/\s+/)
      .filter(Boolean)
      .map((text) => ({ text, strong }));
  });
}

/** Honoured live, not only at load: the setting can change while the page is open. */
function usePrefersStill(): boolean {
  const [still, setStill] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const onChange = (): void => setStill(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return still;
}
