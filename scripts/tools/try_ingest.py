"""Upload one real file into your documents and wait for it to become ready.

    uv run python scripts/tools/try_ingest.py path/to/file.pdf [--email x --password y]

Needs `scripts/stack.sh dev up`. Prints passage count, Qdrant point count and timing.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

from mycel.infra.postgres.repositories.documents import DocumentRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors import documents as vectors

BASE = "http://127.0.0.1:8000"


def login(client: httpx.Client, email: str, password: str) -> None:
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()


async def counts(document_id: int) -> tuple[int, int]:
    async with session_scope() as session:
        chunks = await DocumentRepository(session).count_chunks(document_id)
    return chunks, await vectors.count(document_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--email", default="ingest-try@example.com")
    parser.add_argument("--password", default="ingest try password")
    args = parser.parse_args()

    with httpx.Client(base_url=BASE, timeout=60) as client:
        login(client, args.email, args.password)
        started = time.monotonic()
        with args.file.open("rb") as handle:
            response = client.post(
                "/documents",
                files={"file": (args.file.name, handle)},
            )
        print("upload:", response.status_code, response.json())
        if response.status_code != 202:
            return 1
        document_id = response.json()["id"]

        while True:
            docs = client.get("/documents").json()
            doc = next(d for d in docs if d["id"] == document_id)
            if doc["status"] in ("ready", "failed"):
                break
            time.sleep(2)

    chunks, points = asyncio.run(counts(document_id))
    print(f"status={doc['status']} reason={doc['fail_reason']} pages={doc['pages']}")
    print(f"chunks={chunks} points={points} seconds={time.monotonic() - started:.0f}")
    return 0 if doc["status"] == "ready" and chunks == points else 1


if __name__ == "__main__":
    sys.exit(main())
