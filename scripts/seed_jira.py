"""Fill a fresh Jira project with the work this repository has actually done.

Written because Jira only knows what has been entered into it, and batches 011 through
015 happened before there was a Jira. Without this, the first sync reads an empty project
and every downstream query is untestable.

Two things cannot be back-dated through the REST API, so nothing here pretends otherwise:

  created         stamped by Jira at the moment of the call, read-only
  status history  same, which is why `gold` has no transition table

A worklog's `started` *is* settable, which makes logged effort the one honest time series
in a back-filled project. Estimates, due dates and the epic/story hierarchy are facts about
the plan rather than about time, so they back-fill cleanly.

Every issue is labelled `backfill`. A report that cannot tell invented history from real
history is a report that quietly lies, and the label is how gold can tell.

Idempotent: an issue whose summary is already in the project is left alone, so a second run
adds only what is missing.
"""

import os
import sys
from datetime import date, timedelta
from typing import Any

import httpx

BASE = os.environ["JIRA_BASE_URL"].rstrip("/")
AUTH = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
PROJECT = os.environ.get("JIRA_PROJECT_KEY") or "MYC"
LABEL = "backfill"

TODAY = date.today()


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def ahead(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


#: (summary, estimate, due, done, [(days_ago, time_spent)])
Story = tuple[str, str, str | None, bool, list[tuple[int, str]]]

PLAN: list[tuple[str, str, list[Story]]] = [
    (
        "Pipeline and storage",
        "Bronze, silver and gold in Postgres, with migrations that run themselves.",
        [
            (
                "Postgres schemas and alembic migrations",
                "2d",
                ago(12),
                True,
                [(13, "5h"), (12, "3h")],
            ),
            (
                "Source connector and ETL to gold",
                "3d",
                ago(9),
                True,
                [(11, "6h"), (10, "4h"), (9, "5h")],
            ),
            ("Scheduler syncs on a timer", "1d", ago(8), True, [(8, "4h")]),
        ],
    ),
    (
        "Accounts and the product surfaces",
        "Somewhere durable for a report to live, and pages to read it on.",
        [
            ("Users, sessions and an HttpOnly cookie", "2d", ago(6), True, [(7, "6h"), (6, "4h")]),
            ("Summary report reads gold", "3d", ago(4), True, [(5, "5h"), (4, "6h")]),
            (
                "Router, home page and the account menu",
                "3d",
                ago(1),
                True,
                [(3, "6h"), (2, "5h"), (1, "4h")],
            ),
            ("Dashboard ported into the design system", "2d", ahead(2), False, [(1, "3h")]),
        ],
    ),
    (
        "Jira as the source of record",
        "Replace the hashtag convention with a real work tracker.",
        [
            ("Jira connector and gold.work_item", "3d", ahead(3), False, [(0, "2h")]),
            ("Summariser reads work items", "2d", ahead(5), False, []),
            ("Telegram sends, Calendar shows", "2d", ahead(8), False, []),
        ],
    ),
]


def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    res = httpx.request(method, f"{BASE}/rest/api/3{path}", auth=AUTH, json=body, timeout=30.0)
    if res.status_code >= 400:
        raise SystemExit(f"{method} {path} -> {res.status_code}: {res.text[:400]}")
    return res.json() if res.content else None


def existing() -> dict[str, str]:
    """Summary -> key, for everything already in the project.

    `/search/jql` pages with an opaque token rather than an offset, and stops when it
    stops handing one back.
    """
    found: dict[str, str] = {}
    token: str | None = None
    while True:
        body: dict[str, Any] = {
            "jql": f"project = {PROJECT}",
            "fields": ["summary"],
            "maxResults": 100,
        }
        if token:
            body["nextPageToken"] = token
        page = call("POST", "/search/jql", body)
        for issue in page.get("issues", []):
            found[issue["fields"]["summary"]] = issue["key"]
        token = page.get("nextPageToken")
        if not token:
            return found


def create(
    kind: str,
    summary: str,
    description: str,
    *,
    parent: str | None = None,
    estimate: str | None = None,
    due: str | None = None,
    account_id: str | None = None,
) -> str:
    fields: dict[str, Any] = {
        "project": {"key": PROJECT},
        "issuetype": {"name": kind},
        "summary": summary,
        "labels": [LABEL],
        "description": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        },
    }
    if parent:
        fields["parent"] = {"key": parent}
    if estimate:
        fields["timetracking"] = {"originalEstimate": estimate}
    if due:
        fields["duedate"] = due
    if account_id:
        fields["assignee"] = {"accountId": account_id}
    return str(call("POST", "/issue", {"fields": fields})["key"])


def log_work(key: str, days_ago: int, spent: str) -> None:
    """Effort on the day it happened. `started` is the field Jira lets us choose."""
    started = f"{ago(days_ago)}T09:00:00.000+0000"
    call(
        "POST",
        f"/issue/{key}/worklog?adjustEstimate=leave",
        {"started": started, "timeSpent": spent},
    )


def resolve(key: str) -> None:
    """Move an issue to the first transition whose target is a done-category status."""
    for option in call("GET", f"/issue/{key}/transitions")["transitions"]:
        if option["to"]["statusCategory"]["key"] == "done":
            call("POST", f"/issue/{key}/transitions", {"transition": {"id": option["id"]}})
            return
    print(f"  ! {key}: no done transition", file=sys.stderr)


def main() -> None:
    me = call("GET", "/myself")["accountId"]
    seen = existing()
    print(f"{PROJECT}: {len(seen)} issues already there")

    for epic_summary, epic_note, stories in PLAN:
        epic = seen.get(epic_summary)
        if epic is None:
            epic = create("Epic", epic_summary, epic_note, account_id=me)
            print(f"epic  {epic}  {epic_summary}")

        for summary, estimate, due, done, worklogs in stories:
            if summary in seen:
                continue
            key = create(
                "Story",
                summary,
                epic_note,
                parent=epic,
                estimate=estimate,
                due=due,
                account_id=me,
            )
            for days_ago, spent in worklogs:
                log_work(key, days_ago, spent)
            if done:
                resolve(key)
            print(f"  story {key}  {summary}  ({estimate}, due {due}, {len(worklogs)} worklogs)")


if __name__ == "__main__":
    main()
