/** The project as numbers, polled; one report read top to bottom. */

import { Shell } from "../../components/Shell";
import { KindBreakdown, PriorityBreakdown, StatusOverview } from "./Breakdowns";
import { Effort } from "./Effort";
import { Lede } from "./Lede";
import { Picker } from "./Picker";
import { Epics, Sprints } from "./Progress";
import { PastDue, Recent, Workload } from "./Tables";
import { CATEGORIES } from "./format";
import { useDashboard } from "./useDashboard";

export default function Dashboard() {
  const { projects, board, failure, project, window_, pick } = useDashboard();
  const all = board ? CATEGORIES.reduce((n, c) => n + (board.all_totals[c] ?? 0), 0) : 0;
  const win = `${window_} days`;

  return (
    <Shell>
      <div className="page board">
        <Picker projects={projects} project={project} window_={window_} pick={pick} />

        {failure && <p className="failure">{failure}</p>}

        {projects?.length === 0 && (
          <p className="note">
            Nothing has synced yet. Fill the Jira variables in <code>.env</code>, then run{" "}
            <code>scripts/stack.sh sync</code>.
          </p>
        )}

        {board && (
          <>
            <Lede board={board} all={all} />
            <div className="grid">
              <StatusOverview board={board} win={win} />
              <PriorityBreakdown board={board} />
              <KindBreakdown board={board} />
              <Effort board={board} win={win} />
              <PastDue board={board} />
              <Workload board={board} win={win} />
              <Sprints board={board} />
              <Epics board={board} window_={window_} />
              <Recent board={board} />
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}
