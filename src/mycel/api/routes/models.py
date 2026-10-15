"""The models a person may pick: list, toggle, default."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from mycel.api.dependencies import CurrentUser
from mycel.services import models as domain

router = APIRouter(prefix="/models", tags=["models"])


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
