import sqlalchemy as sa


def test_real_postgres_is_available_and_supports_the_queue_primitives(pg_engine):
    with pg_engine.begin() as c:
        assert c.execute(sa.text("select current_setting('server_version_num')::int")).scalar() >= 160000
        c.execute(sa.text("create temp table q(id int primary key, status text, p jsonb)"))
        c.execute(
            sa.text("insert into q values (1,'queued',cast(:j as jsonb)),(2,'queued','{}')"),
            {"j": '{"a": 1}'},
        )
        first = c.execute(
            sa.text("select id from q where status='queued' order by id for update skip locked limit 1")
        ).scalar()
        assert first == 1
        assert c.execute(sa.text("select p->>'a' from q where id=1")).scalar() == "1"
