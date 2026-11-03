"""Worker only: decrypt a user's keys for one job and build the environment of its child process.

Keys exist in plaintext only in this process's memory and in the child's environment: never on disk, in a
job's payload, progress or error, or in a log. Every decrypted value is registered for redaction (runner.redact)
until the job ends.
"""

import os

from sqlalchemy import select

from .db.models import UserSecret
from .runner import add_job_secrets
from .usersecrets import PROVIDERS, missing_message

CACHE_NAMESPACE_ENV = "RESEARCH_CACHE_NAMESPACE"


class KeyMissing(ValueError):
    """A step needs a provider key the user has not saved (safe to show: names the provider, never a value)."""


def decrypt_keys(db, settings, user_id):
    """{provider: plaintext} of the user's saved keys. A key that no longer decrypts (the master key changed)
    is left out, so the step that needs it is blocked with the usual message."""
    from cryptography.fernet import Fernet, InvalidToken

    if user_id is None or not settings.secrets_key:
        return {}
    fernet = Fernet(settings.secrets_key)
    keys = {}
    for row in db.scalars(select(UserSecret).where(UserSecret.user_id == user_id)):
        if row.provider not in PROVIDERS:
            continue
        try:
            keys[row.provider] = fernet.decrypt(row.ciphertext.encode()).decode()
        except InvalidToken:
            continue
    add_job_secrets(keys.values())
    return keys


def worker_keys(env=None):
    """{provider: value} of the worker's own environment (used only in development mode)."""
    env = os.environ if env is None else env
    return {p.id: env[p.env] for p in PROVIDERS.values() if env.get(p.env)}


def job_keys(db, settings, user_id, env=None):
    """The keys a job runs with: the user's; in development mode the worker's own fill the gaps."""
    keys = decrypt_keys(db, settings, user_id)
    if settings.dev_mode:
        keys = {**worker_keys(env), **keys}
    return keys


def require(keys, providers):
    for provider in sorted(p for p in providers if p):
        if provider in PROVIDERS and provider not in keys:
            raise KeyMissing(missing_message(provider))


def job_environment(base, keys, user_id, dev_mode):
    """The child's environment: `base` without any provider key variable (unless in development mode),
    then the job's keys under the variables the pipeline reads, and the cache namespace (the user id)."""
    env = dict(base)
    if not dev_mode:
        for provider in PROVIDERS.values():
            env.pop(provider.env, None)
    for provider, value in keys.items():
        env[PROVIDERS[provider].env] = value
    if user_id is not None:
        env[CACHE_NAMESPACE_ENV] = str(user_id)
    return env
