import type { Dashboard as Board, WorkItem } from "../../api";
import { Head } from "./Parts";
import { ago, days } from "./format";

export function PastDue({ board }: { board: Board }) {
  return (
    <section className="block wide">
      <Head label="Past due" count={board.overdue.length} scope="whole project" tone="late" />
      {board.overdue.length === 0 ? (
        <p className="empty">nothing is past its due date</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th className="key">issue</th>
              <th>summary</th>
              <th className="who">assignee</th>
              <th className="when">due</th>
            </tr>
          </thead>
          <tbody>
            {board.overdue.map((item: WorkItem) => (
              <tr key={item.issue_key}>
                <td className="key" data-status="late">
                  {item.issue_key}
                </td>
                <td>{item.title}</td>
                <td className="who">{item.assignee_name ?? "Unassigned"}</td>
                <td className="when">
                  {item.due_at ? new Date(item.due_at).toLocaleDateString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function Workload({ board, win }: { board: Board; win: string }) {
  return (
    <section className="block wide">
      <Head label="Team workload" scope={win} />
      {board.assignees.length === 0 ? (
        <p className="empty">nobody has work in this window</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>person</th>
              <th className="n">items</th>
              <th className="n">done</th>
              <th className="n">est</th>
              <th className="n">spent</th>
              <th className="n">gap</th>
            </tr>
          </thead>
          <tbody>
            {board.assignees.map((person) => (
              <tr key={person.name}>
                <td>{person.name}</td>
                <td className="n">{person.items}</td>
                <td className="n" data-status="done">
                  {person.done}
                </td>
                <td className="n">{days(person.estimated_seconds)}</td>
                <td className="n">{days(person.spent_seconds)}</td>
                <td className="n" data-status={person.gap_seconds > 0 ? "late" : "done"}>
                  {days(person.gap_seconds)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="caption">
        The window picks <b>which tickets</b>; the figures are Jira's totals for each ticket's whole
        life. <b>Gap is spent minus estimated</b> — positive is over.
      </p>
    </section>
  );
}

export function Recent({ board }: { board: Board }) {
  return (
    <section className="block wide">
      <Head label="Recent activity" scope="latest, any date" />
      {board.recent.length === 0 ? (
        <p className="empty">nothing has moved in this project yet</p>
      ) : (
        <ol className="feed">
          <li className="heading" aria-hidden="true">
            <span className="key">issue</span>
            <span className="title">summary</span>
            <span className="state">status</span>
            <span className="who">assignee</span>
            <span className="when">updated</span>
          </li>
          {board.recent.map((item) => (
            <li key={item.issue_key}>
              <span className="key">{item.issue_key}</span>
              <span className="title">{item.title}</span>
              <span className="state" data-status={item.status_category}>
                {item.status}
              </span>
              <span className="who">{item.assignee_name ?? "Unassigned"}</span>
              <span className="when">{ago(item.updated_at)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
