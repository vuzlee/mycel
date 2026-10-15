"""The worker side of an own model's Test button: one tiny request per key, results kept."""

from dataclasses import asdict

from mycel.domains.chat_model import test_keys
from mycel.infra.redis import key_checks
from mycel.queue.job import Job


async def run(job: Job) -> None:
    owner_id = job.payload.get("user_id")
    model_ref = job.payload.get("model_ref")
    if not isinstance(owner_id, int) or not isinstance(model_ref, str):
        raise ValueError("key check job needs user_id and model_ref")
    checks = await test_keys(owner_id, model_ref)
    await key_checks.store(job.job_id, owner_id, [asdict(c) for c in checks])
