"""Review panel versioning: reviewer profiles and review settings.

Every save is a new version; old versions are never changed. A reviewer's `current_version` is the last version
a user saved; the current review settings are the highest settings version not created by the importer. A version
the importer creates for an unknown snapshot (`note = "imported"`) never becomes current, except for a reviewer it
had to create. `review_dict` builds a run's `review.json` and validates it with the pipeline's own `ReviewSpec`,
so saved settings are always runnable.
"""

import re
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select

from ..panel import DEFAULT_EDITOR, DEFAULT_PANEL, default_review
from ..schemas import ChecklistItem, ReviewerSpec, ReviewSpec, Thresholds
from .db.models import ReviewerProfile, ReviewerVersion, SettingsVersion, WorkerStatus

UPLOAD_MAX_MB = 30  # hard cap; settings may lower it
KEY = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
ROLE_MODELS = ("plan", "screen", "screen_criteria", "extract")
IMPORTED = "imported"


class ReviewConflict(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def validation_message(exc):
    """The pipeline's validation errors in one line: `loc: message; …`."""
    parts = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error["loc"])
        parts.append(f"{where}: {error['msg']}" if where else error["msg"])
    return "; ".join(parts)[:500]


# --- reviewers -----------------------------------------------------------------------------------------------


def key_from_name(name):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30].rstrip("_")
    if not KEY.match(slug):
        slug = ("reviewer_" + slug)[:30].rstrip("_")
    return slug if KEY.match(slug) else "reviewer"


def item_dicts(reviewer_key, items):
    """Checklist items as stored (every field); missing keys become `<first letter><n>`, skipping used ones."""
    used = {item.key for item in items if item.key}
    prefix, n, out = reviewer_key[0], 0, []
    for item in items:
        key = item.key
        if not key:
            n += 1
            while f"{prefix}{n}" in used:
                n += 1
            key = f"{prefix}{n}"
            used.add(key)
        out.append(
            {
                "key": key,
                "text": item.text,
                "weight": item.weight,
                "source": item.source,
                "pass_if": item.pass_if,
                "red_flag_if": item.red_flag_if,
            }
        )
    return out


def normal_items(items):
    return [ChecklistItem.model_validate(item).model_dump() for item in items]


def reviewer_entry(key, version):
    """One `panel[]` entry of review.json."""
    return {
        "key": key,
        "name": version.name,
        "version": version.version,
        "perspective": version.perspective,
        "model": version.model,
        "items": version.items,
    }


def check_reviewer(key, content):
    try:
        ReviewerSpec.model_validate({"key": key, "version": 1, **content})
    except ValidationError as exc:
        raise ReviewConflict(422, "invalid_reviewer", validation_message(exc)) from None


def get_profile(db, key):
    return db.scalar(select(ReviewerProfile).where(ReviewerProfile.key == key))


def get_reviewer_version(db, profile, number=None):
    return db.scalar(
        select(ReviewerVersion).where(
            ReviewerVersion.profile_id == profile.id,
            ReviewerVersion.version == (number or profile.current_version),
        )
    )


def _next_reviewer_number(db, profile):
    found = db.scalar(
        select(func.max(ReviewerVersion.version)).where(ReviewerVersion.profile_id == profile.id)
    )
    return (found or 0) + 1


def add_reviewer_version(db, profile, content, note, created_by):
    version = ReviewerVersion(
        profile_id=profile.id,
        version=_next_reviewer_number(db, profile),
        name=content["name"],
        perspective=content["perspective"],
        model=content["model"],
        items=content["items"],
        note=note,
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    return version


def _body_content(key, body):
    return {
        "name": body.name,
        "perspective": body.perspective,
        "model": body.model,
        "items": item_dicts(key, body.items),
    }


def create_reviewer(db, body, user_id):
    if body.key:
        key = body.key
        if get_profile(db, key) is not None:
            raise ReviewConflict(409, "key_taken", f"A reviewer with the key {key!r} already exists")
    else:
        base, key, n = key_from_name(body.name), key_from_name(body.name), 1
        while get_profile(db, key) is not None:
            n += 1
            key = f"{base[: 30 - len(str(n)) - 1]}_{n}"
    content = _body_content(key, body)
    check_reviewer(key, content)
    profile = ReviewerProfile(key=key, current_version=1, created_by=user_id)
    db.add(profile)
    db.flush()
    add_reviewer_version(db, profile, content, body.note, user_id)
    return profile


def save_reviewer(db, profile, body, base_version, user_id):
    """Optimistic concurrency: the row is locked, then `base_version` must equal `current_version`."""
    db.refresh(profile, with_for_update=True)
    if profile.archived_at is not None:
        raise ReviewConflict(409, "archived", "This reviewer is archived; restore it first")
    if base_version != profile.current_version:
        raise ReviewConflict(
            409,
            "stale_version",
            f"This reviewer changed since you opened it (now v{profile.current_version})",
        )
    content = _body_content(profile.key, body)
    check_reviewer(profile.key, content)
    version = add_reviewer_version(db, profile, content, body.note, user_id)
    profile.current_version = version.version
    db.flush()
    return version


def set_reviewer_archived(db, profile, archived):
    if archived and profile.key in current_settings(db).default_panel:
        raise ReviewConflict(409, "in_default_panel", "Remove this reviewer from the default panel first")
    profile.archived_at = datetime.now(UTC) if archived else None
    db.flush()
    return profile


def default_reviewer(key):
    """The seeded content of a default reviewer ("Reset to default"), or None."""
    for reviewer in DEFAULT_PANEL:
        if reviewer["key"] == key:
            return {k: reviewer[k] for k in ("name", "perspective", "model", "items")}
    return None


# --- settings ------------------------------------------------------------------------------------------------


def default_settings_content(contact=None):
    return {
        "models": dict.fromkeys(ROLE_MODELS),
        "screening": Thresholds().model_dump(),
        "fulltext": {**default_review(contact)["fulltext"], "upload_max_mb": UPLOAD_MAX_MB},
        "default_panel": [r["key"] for r in DEFAULT_PANEL],
        "editor": dict(DEFAULT_EDITOR),
    }


def settings_content(row):
    return {
        "models": row.models,
        "screening": row.screening,
        "fulltext": row.fulltext,
        "default_panel": row.default_panel,
        "editor": row.editor,
    }


def current_settings(db):
    row = db.scalar(
        select(SettingsVersion)
        .where(SettingsVersion.imported.is_(False))
        .order_by(SettingsVersion.version.desc())
        .limit(1)
    )
    if row is None:  # the migration seeds version 1; recreate it if someone deleted every row
        row = _add_settings(db, default_settings_content(), "default", None, imported=False)
    return row


def _add_settings(db, content, note, created_by, imported):
    number = (db.scalar(select(func.max(SettingsVersion.version))) or 0) + 1
    row = SettingsVersion(version=number, note=note, imported=imported, created_by=created_by, **content)
    db.add(row)
    db.flush()
    return row


def panel_versions(db, keys):
    """The current version of each reviewer in `keys` (in order); 422 when one is unknown or archived."""
    found = []
    for key in keys:
        profile = get_profile(db, key)
        if profile is None or profile.archived_at is not None:
            raise ReviewConflict(422, "invalid_settings", f"Reviewer {key!r} does not exist or is archived")
        found.append((profile, get_reviewer_version(db, profile)))
    return found


def review_dict(content, reviewers):
    """review.json for `content` (settings) and `reviewers` [(profile, version)], validated by ReviewSpec."""
    fulltext = {k: v for k, v in content["fulltext"].items() if k != "upload_max_mb"}
    spec = {
        "schema": 1,
        "panel": [reviewer_entry(profile.key, version) for profile, version in reviewers],
        "editor": content["editor"],
        "models": content["models"],
        "screening": content["screening"],
        "fulltext": fulltext,
    }
    try:
        return ReviewSpec.model_validate(spec).model_dump(mode="json", by_alias=True)
    except ValidationError as exc:
        raise ReviewConflict(422, "invalid_settings", validation_message(exc)) from None


def save_settings(db, content, note, base_version, user_id):
    current = current_settings(db)
    db.refresh(current, with_for_update=True)
    latest = current_settings(db)
    if base_version != latest.version:
        raise ReviewConflict(
            409, "stale_version", f"The review settings changed since you opened them (now v{latest.version})"
        )
    review_dict(content, panel_versions(db, content["default_panel"]))
    return _add_settings(db, content, note, user_id, imported=False)


def review_for_run(db):
    """(review.json dict, settings version, [reviewer versions]) for a new run."""
    settings = current_settings(db)
    reviewers = panel_versions(db, settings.default_panel)
    return review_dict(settings_content(settings), reviewers), settings, [v for _, v in reviewers]


# --- importer linking ----------------------------------------------------------------------------------------


def _comparable(content):
    fulltext = {k: v for k, v in content["fulltext"].items() if k != "upload_max_mb"}
    return {**content, "fulltext": fulltext}


def settings_from_review(review):
    models = review.get("models") or {}
    return {
        "models": {role: models.get(role) for role in ROLE_MODELS},
        "screening": review.get("screening") or Thresholds().model_dump(),
        "fulltext": {**review["fulltext"], "upload_max_mb": UPLOAD_MAX_MB},
        "default_panel": [r["key"] for r in review["panel"]],
        "editor": review["editor"],
    }


def _reviewer_comparable(entry):
    return {
        "name": entry["name"],
        "perspective": entry["perspective"],
        "model": entry.get("model"),
        "items": normal_items(entry["items"]),
    }


def link_reviewer(db, entry, created_by):
    """The reviewer version a snapshot's panel entry used: same content (the numbered version first), else a
    new imported version (current only when the importer had to create the reviewer)."""
    wanted = _reviewer_comparable(entry)
    profile = get_profile(db, entry["key"])
    if profile is not None:
        same = [
            v
            for v in db.scalars(
                select(ReviewerVersion)
                .where(ReviewerVersion.profile_id == profile.id)
                .order_by(ReviewerVersion.version)
            )
            if _reviewer_comparable(reviewer_entry(profile.key, v)) == wanted
        ]
        if same:
            exact = [v for v in same if v.version == entry.get("version")]
            return (exact or same)[0]
        return add_reviewer_version(db, profile, wanted, IMPORTED, created_by)
    profile = ReviewerProfile(key=entry["key"], current_version=1, created_by=created_by)
    db.add(profile)
    db.flush()
    return add_reviewer_version(db, profile, wanted, IMPORTED, created_by)


def link_review(db, review, created_by=None):
    """(settings version, [reviewer versions]) of an imported panel run's review.json."""
    reviewers = [link_reviewer(db, entry, created_by) for entry in review["panel"]]
    wanted = settings_from_review(review)
    for row in db.scalars(select(SettingsVersion).order_by(SettingsVersion.version.desc())):
        if _comparable(settings_content(row)) == _comparable(wanted):
            return row, reviewers
    return _add_settings(db, wanted, IMPORTED, created_by, imported=True), reviewers


# --- models --------------------------------------------------------------------------------------------------


def provider_of(model):
    return model.split(":", 1)[0] if model and ":" in model else None


def available_models(db):
    """Models the worker is configured with, plus the ones the current settings and reviewers name, each
    marked available when its provider's key was accepted by the worker's last check. Never a key value."""
    rows = list(db.scalars(select(WorkerStatus).order_by(WorkerStatus.role)))
    providers = {}
    for row in rows:
        if not row.provider:
            continue
        entry = providers.setdefault(
            row.provider, {"provider": row.provider, "key_present": False, "seen": []}
        )
        entry["key_present"] = entry["key_present"] or row.key_present
        entry["seen"].append(row.key_accepted)
    for entry in providers.values():
        seen = entry.pop("seen")
        entry["key_accepted"] = True if True in seen else (False if False in seen else None)
    models = {}

    def add(model_id, role=None, in_settings=False):
        entry = models.setdefault(model_id, {"id": model_id, "roles": [], "in_settings": False})
        if role and role not in entry["roles"]:
            entry["roles"].append(role)
        entry["in_settings"] = entry["in_settings"] or in_settings

    for row in rows:
        if row.model:
            add(row.model, role=row.role)
    settings = current_settings(db)
    for model in [*(settings.models or {}).values(), (settings.editor or {}).get("model")]:
        if model:
            add(model, in_settings=True)
    for profile in db.scalars(select(ReviewerProfile).where(ReviewerProfile.archived_at.is_(None))):
        version = get_reviewer_version(db, profile)
        if version is not None and version.model:
            add(version.model, in_settings=True)
    out = []
    for model_id in sorted(models):
        provider = provider_of(model_id)
        accepted = (providers.get(provider) or {}).get("key_accepted")
        out.append({**models[model_id], "provider": provider, "available": accepted is True})
    return {"models": out, "providers": [providers[p] for p in sorted(providers)]}
