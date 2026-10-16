"""The models a person may pick: list, toggle, default."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mycel.api.dependencies import CurrentUser
from mycel.api.limits import per_user
from mycel.services import models as domain
from mycel.services import own_models as own

router = APIRouter(prefix="/models", tags=["models"])

#: Each test spends one request per key of the person's own quota.
TESTS_PER_MINUTE = 6


class ModelChoiceResponse(BaseModel):
    ref: str
    label: str
    source: str
    enabled: bool


class ModelsResponse(BaseModel):
    models: list[ModelChoiceResponse]
    default_ref: str


class ToggleRequest(BaseModel):
    enabled: bool


class DefaultRequest(BaseModel):
    ref: str


def _response(found: domain.Models) -> ModelsResponse:
    return ModelsResponse(
        models=[
            ModelChoiceResponse(ref=c.ref, label=c.label, source=c.source, enabled=c.enabled)
            for c in found.choices
        ],
        default_ref=found.default_ref,
    )


@router.get("", response_model=ModelsResponse)
async def list_models(user: CurrentUser) -> ModelsResponse:
    """Every model this person may pick, with their toggles and default."""
    return _response(await domain.models_for(user.id))


@router.put("/prefs/{ref}", response_model=ModelsResponse)
async def toggle_model(ref: str, body: ToggleRequest, user: CurrentUser) -> ModelsResponse:
    """Turn one model on or off for this person."""
    try:
        return _response(await domain.set_enabled(user.id, ref, body.enabled))
    except domain.UnknownModel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such model") from None
    except domain.LastModel:
        raise HTTPException(status.HTTP_409_CONFLICT, "at least one model must stay on") from None


@router.put("/default", response_model=ModelsResponse)
async def set_default_model(body: DefaultRequest, user: CurrentUser) -> ModelsResponse:
    """The model the composer picks before this person chooses."""
    try:
        return _response(await domain.set_default(user.id, body.ref))
    except domain.UnknownModel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such model, or it is off") from None


class OwnModelRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=200, description="What the endpoint calls it.")
    api_base: str = Field(min_length=8, max_length=500)
    #: On an edit, keys to add after the stored ones; stored keys are never sent back.
    keys: list[str] | None = Field(default=None, max_length=own.MAX_KEYS)


class OwnModelResponse(BaseModel):
    id: int
    ref: str
    label: str
    model_id: str
    api_base: str
    key_hints: list[str]


class PresetsResponse(BaseModel):
    presets: dict[str, str]
    max_models: int
    max_keys: int


def _own(view: own.OwnModelView) -> OwnModelResponse:
    return OwnModelResponse(**asdict(view))


@router.get("/own", response_model=list[OwnModelResponse])
async def list_own_models(user: CurrentUser) -> list[OwnModelResponse]:
    """This person's own models; keys show as their last four characters only."""
    return [_own(v) for v in await own.list_own(user.id)]


@router.get("/own/presets", response_model=PresetsResponse)
async def own_model_presets(user: CurrentUser) -> PresetsResponse:
    return PresetsResponse(presets=own.PRESETS, max_models=own.MAX_MODELS, max_keys=own.MAX_KEYS)


@router.post("/own", response_model=OwnModelResponse, status_code=status.HTTP_201_CREATED)
async def add_own_model(body: OwnModelRequest, user: CurrentUser) -> OwnModelResponse:
    try:
        return _own(
            await own.add_own(user.id, body.label, body.model_id, body.api_base, body.keys or [])
        )
    except own.OwnModelRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.patch("/own/{model_id}", response_model=OwnModelResponse)
async def edit_own_model(
    model_id: int, body: OwnModelRequest, user: CurrentUser
) -> OwnModelResponse:
    try:
        return _own(
            await own.edit_own(
                user.id, model_id, body.label, body.model_id, body.api_base, body.keys
            )
        )
    except own.OwnModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such model") from None
    except own.OwnModelRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.delete("/own/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_own_model(model_id: int, user: CurrentUser) -> None:
    """The model and every key it held are deleted, not hidden."""
    try:
        await own.remove_own(user.id, model_id)
    except own.OwnModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such model") from None


@router.delete("/own/{model_id}/keys/{index}", response_model=OwnModelResponse)
async def remove_own_key(model_id: int, index: int, user: CurrentUser) -> OwnModelResponse:
    """Drop the key at this place in `key_hints`; the last key cannot go."""
    try:
        return _own(await own.remove_key(user.id, model_id, index))
    except own.OwnModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such key") from None
    except own.OwnModelRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


class KeyCheckResponse(BaseModel):
    hint: str
    ok: bool
    kind: str | None
    detail: str


class KeyCheckState(BaseModel):
    job_id: str
    status: Literal["running", "done"]
    checks: list[KeyCheckResponse] = []


@router.post(
    "/own/{model_id}/test",
    response_model=KeyCheckState,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[per_user("model_test", TESTS_PER_MINUTE)],
)
async def test_own_model(model_id: int, user: CurrentUser) -> KeyCheckState:
    """One one-token request per key, run by the worker; poll the returned job."""
    try:
        job_id = await own.start_key_check(user.id, model_id)
    except own.OwnModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such model") from None
    return KeyCheckState(job_id=job_id, status="running")


@router.get("/own/tests/{job_id}", response_model=KeyCheckState)
async def own_model_test_result(job_id: str, user: CurrentUser) -> KeyCheckState:
    try:
        checks = await own.key_check_result(user.id, job_id)
    except own.OwnModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such test") from None
    if checks is None:
        return KeyCheckState(job_id=job_id, status="running")
    return KeyCheckState(
        job_id=job_id, status="done", checks=[KeyCheckResponse(**c) for c in checks]
    )
