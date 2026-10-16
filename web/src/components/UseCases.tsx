/** What Mycel actually does, one card each, with a small scene that plays when it is seen. */

import type { ReactNode } from "react";
import { Board, Calendar, Globe, Mail, Notebook } from "./icons";

interface Case {
  icon: ReactNode;
  title: string;
  body: string;
  ask: string;
  scene: ReactNode;
}

const CASES: Case[] = [
  {
    icon: <Notebook size={16} />,
    title: "Ask your documents",
    body: "Upload a handbook or a spec. Answers quote the passage and link the page.",
    ask: "What does the handbook say about on-call?",
    scene: <DocScene />,
  },
  {
    icon: <Board size={16} />,
    title: "Read the board",
    body: "The week summed up, what is late, who logged what. Charts when numbers help.",
    ask: "What is late right now, and who is it with?",
    scene: <BoardScene />,
  },
  {
    icon: <Calendar size={16} />,
    title: "Book it, after you agree",
    body: "Mycel drafts the event and reads it back. Nothing lands until you say yes.",
    ask: "Book 30 minutes with Ada on Friday.",
    scene: <ConfirmScene />,
  },
  {
    icon: <Mail size={16} />,
    title: "Triage your mail",
    body: "What arrived, what is waiting on you, what can wait.",
    ask: "What came in this week that I have not replied to?",
    scene: <MailScene />,
  },
  {
    icon: <Globe size={16} />,
    title: "Look it up",
    body: "Searches the web and tells you where each line came from.",
    ask: "What changed in the Jira API this year?",
    scene: <WebScene />,
  },
];

export function UseCases() {
  return (
    <ul className="cases">
      {CASES.map((item) => (
        <li key={item.title}>
          <div className="scene" aria-hidden>
            {item.scene}
          </div>
          <div className="copy">
            <span className="glyph">{item.icon}</span>
            <b>{item.title}</b>
            <p>{item.body}</p>
            <span className="ask">“{item.ask}”</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A page; a hypha reaches into one passage and lights it. */
function DocScene() {
  return (
    <svg viewBox="0 0 240 120">
      <rect className="sheet" x="34" y="14" width="78" height="96" rx="6" />
      <path className="line" d="M46 32h54M46 44h46M46 56h54" />
      <rect className="hit" x="42" y="64" width="62" height="14" rx="3" />
      <path className="line" d="M46 88h40" />
      <path className="hypha" d="M206 60C180 60 160 71 108 71" />
      <circle className="node" cx="206" cy="60" r="5" />
      <circle className="tip" cx="108" cy="71" r="3" />
    </svg>
  );
}

/** Bars grow, the late one turns, a node marks it. */
function BoardScene() {
  return (
    <svg viewBox="0 0 240 120">
      <path className="axis" d="M30 100h180" />
      <rect className="bar b1" x="44" y="40" width="22" height="60" rx="4" />
      <rect className="bar b2" x="82" y="58" width="22" height="42" rx="4" />
      <rect className="bar b3" x="120" y="30" width="22" height="70" rx="4" />
      <rect className="bar late b4" x="158" y="72" width="22" height="28" rx="4" />
      <path className="hypha" d="M169 66C169 46 190 30 210 24" />
      <circle className="tip" cx="169" cy="64" r="3" />
    </svg>
  );
}

/** A draft slot appears dashed, then a tick confirms it and it fills. */
function ConfirmScene() {
  return (
    <svg viewBox="0 0 240 120">
      <rect className="sheet" x="40" y="14" width="160" height="92" rx="8" />
      <path className="grid" d="M40 40h160M93 14v92M147 14v92" />
      <rect className="slot" x="99" y="50" width="42" height="34" rx="5" />
      <path className="tick" d="M109 67l7 7 15-15" />
    </svg>
  );
}

/** Envelopes arrive; two are picked out, one dims. */
function MailScene() {
  return (
    <svg viewBox="0 0 240 120">
      <g className="env e1">
        <rect x="40" y="18" width="160" height="22" rx="5" />
        <path d="M40 22l80 10 80-10" />
      </g>
      <g className="env e2 keep">
        <rect x="40" y="48" width="160" height="22" rx="5" />
        <path d="M40 52l80 10 80-10" />
      </g>
      <g className="env e3 dim">
        <rect x="40" y="78" width="160" height="22" rx="5" />
        <path d="M40 82l80 10 80-10" />
      </g>
      <circle className="flag f1" cx="208" cy="29" r="3.5" />
      <circle className="flag f2" cx="208" cy="59" r="3.5" />
    </svg>
  );
}

/** One node, three threads out to the web, each ending in a source. */
function WebScene() {
  return (
    <svg viewBox="0 0 240 120">
      <circle className="globe" cx="60" cy="60" r="26" />
      <path
        className="globe"
        d="M34 60h52M60 34c10 8 14 17 14 26s-4 18-14 26c-10-8-14-17-14-26s4-18 14-26Z"
      />
      <path className="hypha h1" d="M86 60C120 60 140 28 186 28" />
      <path className="hypha h2" d="M86 60h100" />
      <path className="hypha h3" d="M86 60C120 60 140 92 186 92" />
      <rect className="src s1" x="188" y="20" width="30" height="16" rx="4" />
      <rect className="src s2" x="188" y="52" width="30" height="16" rx="4" />
      <rect className="src s3" x="188" y="84" width="30" height="16" rx="4" />
    </svg>
  );
}
