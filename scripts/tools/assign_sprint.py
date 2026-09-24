"""Drag every non-epic board issue into a sprint. A one-off, run by a person.

    uv run python scripts/tools/assign_sprint.py           # show what it would do
    uv run python scripts/tools/assign_sprint.py --apply   # do it

Sprints on this site existed and were empty, so the Sprint progress block had nothing to
draw. This is the operation that fills it: not something the sync can do, because a sprint
is a decision about what the team commits to and nothing in gold knows that.

AN EPIC CANNOT BE PUT IN A SPRINT — Jira refuses, and one epic in the list fails the whole
batch. That is the right rule rather than a limitation: an epic spans several sprints, so
it belongs to none of them. Subtasks are skipped for the same reason in reverse: they
follow their parent and have no standing on the board.

Afterwards run `scripts/stack.sh refetch`. An ordinary sync fetches nothing, because the
bronze watermark asks `updated >= ...` and moving an issue into a sprint from the Agile
API does not always bump `updated` for every one of them.
"""

import sys

import httpx

from mycel.core.config import get_settings

#: The board to read, and the sprint to write into. Both are ids rather than names: a
#: name is renamed and repeats across boards, an id does not.
BOARD = 1
SPRINT = 2

#: Jira's own ceiling for one call to this endpoint.
BATCH = 50

SKIP = {"epic", "subtask", "sub-task"}


def main() -> int:
    apply = "--apply" in sys.argv
    settings = get_settings()
    if apply and not settings.jira_write_enabled:
        print("JIRA_WRITE_ENABLED is off — set it in .env first")
        return 1

    token = settings.jira_api_token
    if not (settings.jira_base_url and settings.jira_email and token):
        print("Jira is not configured — JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN")
        return 1

    base = settings.jira_base_url.rstrip("/")
    auth = (settings.jira_email, token.get_secret_value())

    with httpx.Client(timeout=60, auth=auth) as client:
        issues = client.get(
            f"{base}/rest/agile/1.0/board/{BOARD}/issue",
            params={"maxResults": 200, "fields": "issuetype"},
        ).json()["issues"]

        keys = [
            issue["key"]
            for issue in issues
            if issue["fields"]["issuetype"]["name"].lower() not in SKIP
        ]
        print(f"{len(issues)} on the board, {len(keys)} of them can hold a sprint")

        if not apply:
            print(f"\nDRY RUN — nothing written. Re-run with --apply to fill sprint {SPRINT}.")
            return 0

        for start in range(0, len(keys), BATCH):
            batch = keys[start : start + BATCH]
            response = client.post(
                f"{base}/rest/agile/1.0/sprint/{SPRINT}/issue", json={"issues": batch}
            )
            ok = response.status_code in (200, 204)
            detail = "" if ok else response.text[:200]
            print(f"  {len(batch):3} issues -> {response.status_code} {detail}")
            if not ok:
                return 1

    print("\nDone. Now run: scripts/stack.sh refetch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
