"""Per-user provider keys (Settings → My keys) and model choices (Settings → My models), API side.

The API only encrypts: a key arrives once, is encrypted with Fernet (RESEARCH_SECRETS_KEY) and stored with its
last 4 characters. Nothing here decrypts (that is `keyring`, imported only by the worker), returns or logs a key.
Preflight works from presence flags (a saved row), never from a plaintext value.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from ..sources import REGISTRY
from .db.models import SourceRow, UserModels, UserSecret, WorkerStatus


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # model | jev | source
    env: str  # the variable the pipeline reads (the child process gets the key under this name)
    check_url: str | None = None  # a free listing call that proves the key; None: no cheap check


PROVIDERS = {
    p.id: p
    for p in (
        Provider("anthropic", "Anthropic (Claude)", "model", "ANTHROPIC_API_KEY", "anthropic"),
        Provider("google_genai", "Google (Gemini)", "model", "GOOGLE_API_KEY", "google_genai"),
        Provider("openai", "OpenAI (GPT)", "model", "OPENAI_API_KEY", "openai"),
        Provider("xai", "xAI (Grok)", "model", "XAI_API_KEY", "xai"),
        Provider("typesafe", "TypeSafe (Jev)", "jev", "TYPESAFE_API_KEY"),
        Provider("semantic_scholar", "Semantic Scholar", "source", "S2_API_KEY"),
        Provider("core", "CORE", "source", "CORE_API_KEY"),
        Provider("ieee", "IEEE Xplore", "source", "IEEE_API_KEY"),
        Provider("springer", "Springer Nature", "source", "SPRINGER_API_KEY"),
        Provider("elsevier", "Scopus / ScienceDirect (Elsevier)", "source", "ELSEVIER_API_KEY"),
    )
}
KEY_ENV = {p.env: p.id for p in PROVIDERS.values()}  # variable -> provider
MIN_KEY, MAX_KEY = 8, 1000

# Offered in My models once the user has a key for the provider (plus whatever the admin settings name).
MODEL_CATALOG = {
    "anthropic": ("anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5", "anthropic:claude-haiku-4-5"),
    "google_genai": (
        "google_genai:gemini-2.5-pro",
        "google_genai:gemini-2.5-flash",
        "google_genai:gemini-3.1-pro-preview",
    ),
    "openai": ("openai:gpt-5", "openai:gpt-5-mini"),
    "xai": ("xai:grok-4", "xai:grok-4-fast"),
}


class SecretsError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def missing_message(provider):
    label = PROVIDERS[provider].label if provider in PROVIDERS else provider
    return f"Add your {label} key in Settings → My keys"


def provider_of(model):
    return model.split(":", 1)[0] if model and ":" in model else None


def source_provider(name):
    """The key provider a source needs (auth required) or can use (optional); None: no key of a user."""
    info = REGISTRY.get(name)
    if info is None or not info.env:
        return None
    return KEY_ENV.get(info.env[0])


# --- storage (encrypt only) ----------------------------------------------------------------------------------


def _fernet(settings):
    from cryptography.fernet import Fernet

    if not settings.secrets_key:
        raise SecretsError(503, "secrets_unavailable", "Saving keys is not configured on this server")
    return Fernet(settings.secrets_key)


def save_secret(db, settings, user_id, provider, value):
    if provider not in PROVIDERS:
        raise SecretsError(404, "not_found", "No such provider")
    value = (value or "").strip()
    if not MIN_KEY <= len(value) <= MAX_KEY or any(c.isspace() for c in value):
        raise SecretsError(422, "invalid_key", f"A key has {MIN_KEY} to {MAX_KEY} characters and no spaces")
    ciphertext = _fernet(settings).encrypt(value.encode()).decode()
    row = db.scalar(select(UserSecret).where(UserSecret.user_id == user_id, UserSecret.provider == provider))
    if row is None:
        row = UserSecret(user_id=user_id, provider=provider)
        db.add(row)
    row.ciphertext, row.last4 = ciphertext, value[-4:]
    row.created_at = datetime.now(UTC)
    row.checked_at, row.check_ok, row.check_detail = None, None, ""
    db.flush()
    return row


def delete_secret(db, user_id, provider):
    row = db.scalar(select(UserSecret).where(UserSecret.user_id == user_id, UserSecret.provider == provider))
    if row is None:
        raise SecretsError(404, "not_found", "No key saved for this provider")
    db.delete(row)
    db.flush()


def secret_rows(db, user_id):
    return {r.provider: r for r in db.scalars(select(UserSecret).where(UserSecret.user_id == user_id))}


def key_list(db, user_id):
    """One entry per provider: label, kind and, when saved, last 4 characters and dates. Never a value."""
    rows = secret_rows(db, user_id)
    out = []
    for provider in PROVIDERS.values():
        row = rows.get(provider.id)
        out.append(
            {
                "provider": provider.id,
                "label": provider.label,
                "kind": provider.kind,
                "saved": row is not None,
                "last4": row.last4 if row else None,
                "created_at": row.created_at if row else None,
                "checked_at": row.checked_at if row else None,
                "check_ok": row.check_ok if row else None,
                "check_detail": (row.check_detail or "") if row else "",
                "checkable": provider.check_url is not None,
            }
        )
    return out


# --- presence (preflight) ------------------------------------------------------------------------------------


def worker_providers(db):
    """Providers whose key the worker's own environment holds (development mode only stands in with them)."""
    found = {
        row.provider for row in db.scalars(select(WorkerStatus).where(WorkerStatus.key_present.is_(True)))
    }
    for row in db.scalars(select(SourceRow).where(SourceRow.key_present.is_(True))):
        if (provider := source_provider(row.name)) is not None:
            found.add(provider)
    return {p for p in found if p}


def usable_providers(db, settings, user_id):
    """Providers this user can use: the keys they saved, and in development mode the worker's own."""
    usable = set(secret_rows(db, user_id))
    if settings.dev_mode:
        usable |= worker_providers(db)
    return usable


def _worker_model(db, role):
    row = db.get(WorkerStatus, role)
    return row.model if row else None


def run_models_needed(db, review):
    """Every model a panel run will call: review.json's, else the worker's model for that role."""
    from .review import ROLE_MODELS

    models = review.get("models") or {}
    needed = [models.get(role) or _worker_model(db, role) for role in ROLE_MODELS]
    needed += [entry.get("model") or _worker_model(db, "review_a") for entry in review.get("panel") or []]
    needed.append((review.get("editor") or {}).get("model") or _worker_model(db, "adjudicate"))
    return [m for m in needed if m]


def needed_for_run(db, review, domain):
    """Providers a live run cannot do without: its models' providers and the sources that require a key."""
    needed = {provider_of(m) for m in run_models_needed(db, review or {})} if review else set()
    if not review:
        needed |= {provider_of(_worker_model(db, role)) for role in ("plan", "screen", "extract")}
    for source in (domain or {}).get("sources") or []:
        name = source.get("name") if isinstance(source, dict) else source
        info = REGISTRY.get(name)
        if info is not None and info.auth == "required":
            needed.add(source_provider(name))
    return {p for p in needed if p in PROVIDERS}


def preflight(db, settings, user_id, providers):
    """Raise when the user lacks a key a step needs (presence only, never a value)."""
    usable = usable_providers(db, settings, user_id)
    for provider in sorted(p for p in providers if p):
        if provider in PROVIDERS and provider not in usable:
            raise SecretsError(422, "key_missing", missing_message(provider))


# --- models per user -----------------------------------------------------------------------------------------

ROLE_LABELS = {
    "plan": "Search plan",
    "screen": "Screen",
    "screen_criteria": "Screen by criteria",
    "extract": "Extract",
    "editor": "Editor",
    "reader": "Reader and paper map",
}


def user_choices(db, user_id):
    row = db.get(UserModels, user_id)
    return dict(row.models or {}) if row else {}


def role_defaults(db):
    """[(role, label, admin default or None)] for every role a user can choose a model for."""
    from .review import ROLE_MODELS, current_settings, get_profile, get_reviewer_version

    settings = current_settings(db)
    models = settings.models or {}
    roles = [(role, ROLE_LABELS[role], models.get(role) or _worker_model(db, role)) for role in ROLE_MODELS]
    for key in settings.default_panel or []:
        profile = get_profile(db, key)
        version = get_reviewer_version(db, profile) if profile else None
        if version is not None:
            roles.append((f"review:{key}", version.name, version.model or _worker_model(db, "review_a")))
    editor = (settings.editor or {}).get("model") or _worker_model(db, "adjudicate")
    roles.append(("editor", ROLE_LABELS["editor"], editor))
    roles.append(("reader", ROLE_LABELS["reader"], models.get("reader") or models.get("screen")))
    return roles


def model_options(db, settings, user_id):
    """Models a user may pick: the catalog plus the models the admin settings name, each marked available
    when the user can use its provider."""
    from .review import available_models

    usable = usable_providers(db, settings, user_id)
    ids = {m for ids in MODEL_CATALOG.values() for m in ids}
    ids |= {m["id"] for m in available_models(db)["models"] if provider_of(m["id"]) in PROVIDERS}
    ids |= {d for _r, _l, d in role_defaults(db) if d and provider_of(d) in PROVIDERS}
    return [
        {"id": m, "provider": provider_of(m), "available": provider_of(m) in usable}
        for m in sorted(ids)
        if provider_of(m) in PROVIDERS and PROVIDERS[provider_of(m)].kind == "model"
    ]


def my_models(db, settings, user_id):
    choices = user_choices(db, user_id)
    roles = []
    for role, label, default in role_defaults(db):
        choice = choices.get(role)
        roles.append(
            {
                "role": role,
                "label": label,
                "default": default,
                "choice": choice,
                "effective": choice or default,
            }
        )
    return {"roles": roles, "options": model_options(db, settings, user_id)}


def save_models(db, settings, user_id, choices):
    """Replace the user's choices; null or a missing role means the admin default. Only offered models of a
    provider the user has a key for."""
    roles = {role for role, _l, _d in role_defaults(db)}
    options = {o["id"]: o for o in model_options(db, settings, user_id)}
    clean = {}
    for role, model in (choices or {}).items():
        if role not in roles:
            raise SecretsError(422, "invalid_models", f"Unknown role {role!r}")
        if not model:
            continue
        if model not in options:
            raise SecretsError(422, "invalid_models", f"{model!r} is not one of the offered models")
        if not options[model]["available"]:
            raise SecretsError(422, "key_missing", missing_message(provider_of(model)))
        clean[role] = model
    row = db.get(UserModels, user_id)
    if row is None:
        row = UserModels(user_id=user_id, models=clean)
        db.add(row)
    row.models = clean
    db.flush()
    return my_models(db, settings, user_id)


def apply_user_models(review, choices):
    """A copy of review.json with the user's model choices (frozen into the run's request)."""
    from ..schemas import ReviewSpec
    from .review import ROLE_MODELS

    if not choices:
        return review
    review = {
        **review,
        "models": dict(review.get("models") or {}),
        "editor": dict(review.get("editor") or {}),
    }
    for role in ROLE_MODELS:
        if choices.get(role):
            review["models"][role] = choices[role]
    review["panel"] = [
        {**entry, "model": choices.get(f"review:{entry['key']}") or entry.get("model")}
        for entry in review.get("panel") or []
    ]
    if choices.get("editor"):
        review["editor"]["model"] = choices["editor"]
    return ReviewSpec.model_validate(review).model_dump(mode="json", by_alias=True)


def reader_choice(db, user_id):
    return user_choices(db, user_id).get("reader")


def assist_model_api(db, user_id):
    """The model the field assistant will use as far as the API can tell: the user's Screen choice, else the
    worker's search-plan model (the worker may still use RESEARCH_ASSIST_MODEL)."""
    return user_choices(db, user_id).get("screen") or _worker_model(db, "plan")
