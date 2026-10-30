"""The /models reads with nothing of mycel around them: what this stack does on this host.

One app, four URLs, the same reads as mycel's /models (session + user, own models, their
keys when there are any, toggles, default) for one token:

    /orm-two   SQLAlchemy ORM, two sessions per request, pool_pre_ping  (mycel's shape)
    /orm-one   SQLAlchemy ORM, one session, no ping
    /core      SQLAlchemy Core on one connection, no ORM objects, no ping
    /raw       asyncpg, one connection, the same SQL

Runs inside the api container so versions match, next to the real api on :8000:

    docker cp scripts/ops/load/baseline.py mycel-api-1:/tmp/
    docker exec -d -w /tmp mycel-api-1 \
        /app/.venv/bin/uvicorn baseline:app --port 8010 --no-access-log

then point k6 (reads.js) at http://localhost:8010 from `--network container:mycel-api-1`.
"""

import asyncpg
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mycel.core.config import get_settings
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.models import ModelPref, OwnModel, OwnModelKey, Session, User

DSN = get_settings().database_url
#: Small on purpose: three pools here plus the api must fit max_connections (100).
POOL = {"pool_size": 10, "max_overflow": 0}

pinged = async_sessionmaker(create_async_engine(async_dsn(DSN), pool_pre_ping=True, **POOL))
core = create_async_engine(async_dsn(DSN), **POOL)
plain = async_sessionmaker(core)
raw: asyncpg.Pool | None = None

app = FastAPI()


@app.on_event("startup")
async def _open() -> None:
    global raw
    raw = await asyncpg.create_pool(
        DSN.replace("postgresql+asyncpg://", "postgresql://"), max_size=10
    )


async def _reads(s, token: str) -> dict:
    found = (
        await s.execute(
            select(Session, User).join(User, User.id == Session.user_id).where(Session.id == token)
        )
    ).first()
    uid = found[1].id
    own = list(
        await s.scalars(select(OwnModel).where(OwnModel.owner_id == uid).order_by(OwnModel.id))
    )
    ids = [m.id for m in own]
    keys = (
        list(await s.scalars(select(OwnModelKey).where(OwnModelKey.own_model_id.in_(ids))))
        if ids
        else []
    )
    rows = await s.execute(
        select(ModelPref.model_ref, ModelPref.enabled).where(ModelPref.user_id == uid)
    )
    toggles = {ref: on for ref, on in rows.tuples()}
    default = await s.scalar(select(User.default_model_ref).where(User.id == uid))
    return {"own": len(own), "keys": len(keys), "toggles": len(toggles), "default": default}


@app.get("/orm-two")
async def orm_two(request: Request) -> dict:
    token = request.cookies["mycel_session"]
    async with pinged() as s:
        await s.execute(
            select(Session, User).join(User, User.id == Session.user_id).where(Session.id == token)
        )
        await s.commit()
    async with pinged() as s:
        out = await _reads(s, token)
        await s.commit()
    return out


@app.get("/orm-one")
async def orm_one(request: Request) -> dict:
    async with plain() as s:
        out = await _reads(s, request.cookies["mycel_session"])
        await s.commit()
    return out


@app.get("/core")
async def core_reads(request: Request) -> dict:
    token = request.cookies["mycel_session"]
    async with core.connect() as c:
        uid = await c.scalar(
            select(User.id).join(Session, Session.user_id == User.id).where(Session.id == token)
        )
        own = (
            await c.execute(
                select(OwnModel.__table__).where(OwnModel.owner_id == uid).order_by(OwnModel.id)
            )
        ).all()
        ids = [r.id for r in own]
        keys = (
            (
                await c.execute(
                    select(OwnModelKey.__table__).where(OwnModelKey.own_model_id.in_(ids))
                )
            ).all()
            if ids
            else []
        )
        toggles = (
            await c.execute(
                select(ModelPref.model_ref, ModelPref.enabled).where(ModelPref.user_id == uid)
            )
        ).all()
        default = await c.scalar(select(User.default_model_ref).where(User.id == uid))
    return {"own": len(own), "keys": len(keys), "toggles": len(toggles), "default": default}


@app.get("/raw")
async def raw_reads(request: Request) -> dict:
    token = request.cookies["mycel_session"]
    assert raw is not None
    async with raw.acquire() as c:
        uid = await c.fetchval(
            "select u.id from app.session s join app.user u on u.id = s.user_id where s.id = $1",
            token,
        )
        own = await c.fetch("select * from app.own_model where owner_id = $1 order by id", uid)
        ids = [r["id"] for r in own]
        keys = (
            await c.fetch(
                "select * from app.own_model_key where own_model_id = any($1::int[])", ids
            )
            if ids
            else []
        )
        toggles = await c.fetch(
            "select model_ref, enabled from app.model_pref where user_id = $1", uid
        )
        default = await c.fetchval("select default_model_ref from app.user where id = $1", uid)
    return {"own": len(own), "keys": len(keys), "toggles": len(toggles), "default": default}
