"""Ask one notebook a real question and print the answer with its sources.

    uv run python scripts/try_ask.py NOTEBOOK_ID "question" [--email x --password y]

Needs `scripts/stack.sh dev up` and a notebook from scripts/try_ingest.py. Spends one
Gemini call unless the answer is cached.
"""

import argparse
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("notebook", type=int)
    parser.add_argument("question")
    parser.add_argument("--email", default="ingest-try@example.com")
    parser.add_argument("--password", default="ingest try password")
    args = parser.parse_args()

    with httpx.Client(base_url=BASE, timeout=60) as client:
        client.post("/auth/login", json={"email": args.email, "password": args.password})
        time.sleep(0.5)
        print("quota left:", client.get("/asks/quota").json()["remaining"])
        response = client.post(f"/notebooks/{args.notebook}/ask", json={"question": args.question})
        body = response.json()
        print("ask:", response.status_code, "cached" if body.get("cached") else body.get("job_id"))
        if response.status_code >= 400:
            print(body)
            return 1
        while body["status"] not in ("done", "failed"):
            time.sleep(2)
            body = client.get(f"/asks/{body['job_id']}").json()

    print(f"\n{body['status'].upper()}\n{body['answer'] or body['error']}\n")
    for source in body["sources"]:
        page = f" p.{source['page']}" if source["page"] else ""
        print(f"  [{source['label']}] {source['filename']}{page} — {source['section']}")
    return 0 if body["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
