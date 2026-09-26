import importlib.util
from pathlib import Path

from sqlalchemy import func, select

from research_agent.web.db.models import Paper, Run, Screening, User
from research_agent.web.db.session import make_engine, make_session_factory
from research_agent.web.settings import load_settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_server.py"


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_server", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_browser_test_dataset_has_the_story_the_specs_rely_on(fresh_db_url, tmp_path):
    e2e = load_script()
    e2e.build_dataset(tmp_path)
    settings = load_settings(e2e.environment(fresh_db_url, tmp_path))
    e2e.seed(settings)
    factory = make_session_factory(make_engine(fresh_db_url))
    with factory() as db:
        assert sorted(role for (role,) in db.execute(select(User.role))) == ["admin", "member", "viewer"]
        kinds = sorted(kind for (kind,) in db.execute(select(Run.kind)))
        assert kinds == ["eval", "research"]
        eval_run = db.scalar(select(Run).where(Run.kind == "eval"))
        paper = db.scalar(select(Paper).where(Paper.source_id == "MED:3"))
        screening = db.scalar(
            select(Screening).where(Screening.run_id == eval_run.id, Screening.paper_id == paper.id)
        )
        assert (screening.tier, screening.decision) == ("jev", "exclude")
        assert (
            db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == eval_run.id))
            == 12
        )
