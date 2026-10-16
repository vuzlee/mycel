/** Ask anything, and watch the run happen. */

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Chip, SourceRef } from "../api";
import { askChat, fetchModels, fetchProjects } from "../api";
import { Answer } from "../components/Answer";
import { buildConversation } from "../lib/buildConversation";
import type { ComposerHandle } from "../components/Composer";
import { Composer } from "../components/Composer";
import { MODELS_KEY } from "../components/panels/ModelsPage";
import { PastTurns } from "../components/PastTurns";
import { Shell } from "../components/Shell";
import { Conversation } from "../components/Conversation";
import { sendFiles } from "../components/knowledge/Documents";
import { SourcePanel } from "../components/knowledge/SourcePanel";
import type { Topic } from "../components/Topics";
import { Topics, anchorFor } from "../components/Topics";
import { Bars, Globe, Mail, People } from "../components/icons";
import { useRun } from "../hooks/useRun";
import { useConversations } from "../context/ConversationsContext";
import { useDocuments } from "../hooks/useDocuments";
import { useHotkey } from "../hooks/useHotkey";
import { usePastTurns } from "../hooks/usePastTurns";
import { useRefetchOnSettle, useScrollToQuestion } from "../hooks/useAskEffects";

//: How far below the top of the body the question is parked. Flush against the edge reads
//: as a page cut off rather than a turn begun. Same number as `.turn.user`'s
//: `scroll-margin-top`, which still serves the map's `scrollIntoView` in `Topics`; this
//: scroll does the arithmetic itself, and a margin has no say in a `scrollTop` we compute.
const TOP_GAP = 24;

// One per capability, because these buttons are the capability documentation people
// actually read — nobody opens the docs before typing a first question. Every screen the
// app still has its own page for is reachable from here too: progress is the summarizer,
// the dashboard's numbers are the analyst writing its own SQL.
//
// The Jira seeds name the reader's own first project, and go when they can read none: a
// seed for a project they cannot see is a button that answers "no access".
interface SeedGroup {
  name: string;
  icon: ReactNode;
  items: string[];
}

const seedGroups = (project: string | null): SeedGroup[] => [
  ...(project
    ? [
        {
          name: "Team",
          icon: <People />,
          items: [
            `How is ${project} going this week?`, // summarizer — the progress summary
            "What is late right now, and who is it with?", // analyst — the dashboard's own question
          ],
        },
        {
          name: "Hours",
          icon: <Bars />,
          items: [
            "Who logged the most hours this month, and on what?", // analyst, through run_sql
            "Compare hours logged this month with last month.", // analyst — two windows, one query
          ],
        },
      ]
    : []),
  {
    name: "Mail",
    icon: <Mail />,
    items: [
      "Anything important in my mail today?", // researcher — read_mail(24)
      "What came in this week that I have not replied to?", // researcher — read_mail(168)
    ],
  },
  {
    name: "Web",
    icon: <Globe />,
    items: [
      "What changed in the Jira API this year?", // researcher — the web
      "What are teams using for AI code review now?", // researcher — the web
    ],
  },
];

export function Ask() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const { reload } = useConversations();

  const [asked, setAsked] = useState<string | null>(null);
  // A fresh object per click, so the same seed picked twice still fills the box.
  // From the Knowledge page's Ask: the box opens naming that document.
  const [seed, setSeed] = useState<{ text: string } | null>(() => {
    const about = params.get("about");
    return about ? { text: `In ${about}, ` } : null;
  });
  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: fetchProjects });
  const firstProject = projects?.[0] ?? null;
  const groups = useMemo(() => seedGroups(firstProject), [firstProject]);
  const [refused, setRefused] = useState<string | null>(null);
  const composer = useRef<ComposerHandle>(null);
  // `?source=knowledge` from the Knowledge page: start with that source picked.
  const [chips, setChips] = useState<Chip[]>(() =>
    params.get("source") === "knowledge" ? ["knowledge"] : [],
  );

  const { data: models } = useQuery({ queryKey: MODELS_KEY, queryFn: fetchModels });
  const usable = useMemo(() => models?.models.filter((m) => m.enabled) ?? [], [models]);
  // The reader's pick for this tab; the default until they choose, and again if it goes off.
  const [picked, setPicked] = useState<string | null>(null);
  const model = usable.some((m) => m.ref === picked) ? picked : (models?.default_ref ?? null);
  const [source, setSource] = useState<SourceRef | null>(null);
  const docs = useDocuments();
  // The scrolling body, as the observer in `Topics` needs it: a root, not a ref, because
  // it arrives one render after the first paint and the observer has to be rebuilt then.
  const [body, setBody] = useState<HTMLElement | null>(null);

  const run = useRun(jobId);
  const followRef = run.follow.ref;
  const scrollRef = useCallback(
    (node: HTMLDivElement | null) => {
      followRef(node);
      setBody(node);
    },
    [followRef],
  );

  // Arriving from the sidebar or a reloaded link: the question is not in this tab's
  // memory, and the stream does not carry it — a stream is tool calls, not the prompt.
  // The run itself says what it was asked, which the conversation cannot: a conversation's title is
  // the question that opened it, and captions every later turn wrongly.
  const question = asked ?? run.result?.question ?? null;

  // The conversation the next question joins. `?conversation=` first because it is there the moment
  // you navigate, while the run needs a poll to come back — and it is the run, not the
  // sidebar, that knows the conversation of a link naming a turn other than the latest.
  const fromUrl = params.get("conversation");
  const conversationId = fromUrl ? Number(fromUrl) : (run.result?.conversation_id ?? null);

  const { past, setPast, pastFor, savedSteps } = usePastTurns(conversationId, jobId);
  // A reopened turn's stream has expired; its trail comes from what was saved instead.
  const items = useMemo(
    () =>
      run.items.length > 0 || !savedSteps || run.busy ? run.items : buildConversation(savedSteps),
    [run.items, run.busy, savedSteps],
  );

  const startNew = useCallback(() => {
    setParams({}, { replace: false });
    setAsked(null);
    setPast([]);
    setRefused(null);
    composer.current?.focus();
  }, [setParams, setPast]);

  useHotkey("k", startNew);

  const ask = async (text: string): Promise<void> => {
    setRefused(null);
    try {
      // The open conversation by default, a new one only when the reader asked for one with
      // `+` or Cmd+K. Continuing is what every other conversation does; splitting is the
      // thing that takes a click.
      const { job_id, conversation_id } = await askChat(
        text,
        conversationId ?? undefined,
        chips,
        model ?? undefined,
      );
      setAsked(text);
      setParams({ job: job_id, conversation: String(conversation_id) });
      reload();
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error));
    }
  };

  const failure = refused ?? run.failure;

  // An answer with sources streamed with its markers hidden. Once it is done, the checked
  // answer - only the markers that held, and clickable sources - takes its place.
  const cited = run.result?.status === "done" && run.result.sources.length > 0;

  useRefetchOnSettle(jobId, run.result?.status, reload);
  useScrollToQuestion(body, jobId, question, pastFor, TOP_GAP);

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
      scrollRef={scrollRef}
      aside={topics.length > 1 ? <Topics topics={topics} root={body} /> : undefined}
      jump={jobId !== null && run.follow.adrift ? run.follow.toBottom : undefined}
      footer={
        <Composer
          busy={run.busy}
          seed={seed}
          handle={composer}
          chips={chips}
          onChips={setChips}
          knowledgeLocked={docs.busy || docs.loading || docs.error !== null}
          models={usable}
          model={model}
          onModel={setPicked}
          onAsk={(text) => void ask(text)}
          onDropFiles={(files) => {
            void sendFiles(files).then((errors) => {
              if (errors.length) setRefused(errors.join(" "));
            });
          }}
        />
      }
    >
      {jobId ? (
        <Conversation
          anchor={anchorFor(jobId)}
          before={past.length > 0 ? <PastTurns turns={past} /> : null}
          question={question}
          items={
            cited ? items.filter((i) => i.kind !== "text" || i.agent !== "orchestrator") : items
          }
          gaps={run.gaps}
          failure={failure}
          pending={run.pending}
        >
          {run.result?.status === "done" && (
            <Answer
              result={run.result}
              streamed={!cited && items.some((i) => i.kind === "text")}
              onSource={setSource}
            />
          )}
        </Conversation>
      ) : (
        <div className="blank">
          <h1>Ask Mycel anything</h1>
          <p>Your team's week, the numbers, your mail, or anything on the web.</p>
          {refused && <p className="failure">{refused}</p>}
          <div className="seed-groups">
            {groups.map((group) => (
              <section key={group.name}>
                <h2>
                  {group.icon}
                  {group.name}
                </h2>
                {group.items.map((text) => (
                  <button key={text} className="seed" onClick={() => setSeed({ text })}>
                    {text}
                  </button>
                ))}
              </section>
            ))}
          </div>
        </div>
      )}
      {source && <SourcePanel source={source} onClose={() => setSource(null)} />}
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
