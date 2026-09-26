import pytest

from research_agent.web.settings import SettingsError, load_settings

BASE = {"RESEARCH_WEB_DATABASE_URL": "postgresql+psycopg://x/y"}


def test_job_settings_have_safe_defaults():
    s = load_settings(BASE)
    assert s.allow_demo is False and s.max_papers_cap == 12 and s.max_active_jobs_per_user == 2
    assert s.job_stale_seconds == 120 and s.job_max_attempts == 3
    assert s.worker_poll_seconds == 2.0 and s.progress_poll_seconds == 2.0


def test_job_settings_can_be_overridden_from_the_environment():
    s = load_settings(
        {
            **BASE,
            "RESEARCH_WEB_ALLOW_DEMO": "true",
            "RESEARCH_WEB_MAX_PAPERS": "5",
            "RESEARCH_WEB_MAX_ACTIVE_JOBS": "1",
            "RESEARCH_WEB_JOB_STALE_SECONDS": "30",
            "RESEARCH_WEB_WORKER_POLL_SECONDS": "0.1",
        }
    )
    assert s.allow_demo is True and s.max_papers_cap == 5 and s.max_active_jobs_per_user == 1
    assert s.job_stale_seconds == 30 and s.worker_poll_seconds == 0.1


@pytest.mark.parametrize(
    "name,value",
    [
        ("RESEARCH_WEB_MAX_PAPERS", "abc"),
        ("RESEARCH_WEB_MAX_PAPERS", "0"),
        ("RESEARCH_WEB_MAX_PAPERS", "31"),
        ("RESEARCH_WEB_WORKER_POLL_SECONDS", "nan"),
        ("RESEARCH_WEB_PROGRESS_POLL_SECONDS", "inf"),
    ],
)
def test_bad_numbers_are_rejected(name, value):
    with pytest.raises(SettingsError, match=name):
        load_settings({**BASE, name: value})
