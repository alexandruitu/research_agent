"""0019: every foreign key has an index that starts with it, so joins and ON DELETE cascades never scan."""

import sqlalchemy as sa

UNINDEXED_FKS = sa.text(
    """
    select c.conrelid::regclass::text as tab, a.attname as col
    from pg_constraint c
    join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
    where c.contype = 'f' and array_length(c.conkey, 1) = 1
      and not exists (
        select 1 from pg_index i where i.indrelid = c.conrelid and i.indkey[0] = c.conkey[1]
      )
    order by 1, 2
    """
)


def test_every_foreign_key_is_indexed(fresh_db_url):
    engine = sa.create_engine(fresh_db_url)
    try:
        with engine.connect() as connection:
            missing = [f"{row.tab}.{row.col}" for row in connection.execute(UNINDEXED_FKS)]
    finally:
        engine.dispose()
    assert missing == []
