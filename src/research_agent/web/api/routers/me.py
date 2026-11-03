"""Settings → My keys, My models, My usage: every member manages their own. Keys are only encrypted here;
no response or log line ever holds a key value (only its last 4 characters)."""

import logging

from fastapi import APIRouter, Depends

from ... import usersecrets
from ...jobs import enqueue
from ...runs import user_usage
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import JobOut, KeyIn, KeyOut, MyModelsIn, MyModelsOut, UsageOut
from .runs import check_active_cap, job_out

router = APIRouter(prefix="/me", tags=["me"])
log = logging.getLogger(__name__)


def _error(exc):
    return ApiError(exc.status, exc.code, exc.message)


def _key(db, user_id, provider, dev_mode=False):
    return next(k for k in usersecrets.key_list(db, user_id, dev_mode) if k["provider"] == provider)


@router.get("/keys", response_model=list[KeyOut])
def list_keys(user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings)):
    return usersecrets.key_list(db, user.id, settings.dev_mode)


@router.put("/keys/{provider}", response_model=KeyOut)
def save_key(
    provider: str,
    body: KeyIn,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Add or replace a key. It is never shown again: the answer carries only its last 4 characters."""
    try:
        usersecrets.save_secret(db, settings, user.id, provider, body.key)
    except usersecrets.SecretsError as exc:
        raise _error(exc) from None
    db.commit()
    log.info("key saved: provider %s by %s", provider, user.id)
    return _key(db, user.id, provider, settings.dev_mode)


@router.delete("/keys/{provider}", status_code=204)
def delete_key(provider: str, user=Depends(require_role("member")), db=Depends(get_db)):
    try:
        usersecrets.delete_secret(db, user.id, provider)
    except usersecrets.SecretsError as exc:
        raise _error(exc) from None
    db.commit()
    log.info("key deleted: provider %s by %s", provider, user.id)


@router.post("/keys/{provider}/check", response_model=JobOut, status_code=202)
def check_key(
    provider: str,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Queue a test of the saved key: the worker (the only process that decrypts) makes one free call."""
    if provider not in usersecrets.PROVIDERS or not _key(db, user.id, provider)["saved"]:
        raise ApiError(404, "not_found", "No key saved for this provider")
    check_active_cap(db, user, settings)
    job, _ = enqueue(db, "secret_check", {"provider": provider}, user.id)
    db.commit()
    return job_out(job)


@router.get("/models", response_model=MyModelsOut)
def get_models(user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings)):
    return usersecrets.my_models(db, settings, user.id)


@router.put("/models", response_model=MyModelsOut)
def put_models(
    body: MyModelsIn,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Replace the user's model choices (null: the admin default). Each new run freezes them in its config."""
    try:
        out = usersecrets.save_models(db, settings, user.id, body.models)
    except usersecrets.SecretsError as exc:
        raise _error(exc) from None
    db.commit()
    return out


@router.get("/usage", response_model=UsageOut)
def usage(user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings)):
    return user_usage(db, settings, user.id)
