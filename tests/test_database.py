import os
import tempfile
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.database import get_engine, get_session, init_db
from app.models import Base, Source, Item


def test_engine_uses_wal_mode():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = get_engine(path)
    with engine.connect() as conn:
        result = conn.execute(sa.text("PRAGMA journal_mode"))
        mode = result.scalar()
        assert mode.upper() == "WAL"
    engine.dispose()
    os.unlink(path)


def test_init_db_creates_tables():
    engine = get_engine(":memory:")
    init_db(engine)
    insp = sa.inspect(engine)
    tables = insp.get_table_names()
    assert "sources" in tables
    assert "items" in tables
    engine.dispose()


def test_source_crud():
    engine = get_engine(":memory:")
    init_db(engine)

    session_cls = get_session(engine)
    with session_cls() as session:
        src = Source(name="Test Blog", url="https://example.com/feed", enabled=True)
        session.add(src)
        session.commit()
        assert src.id is not None

        loaded = session.get(Source, src.id)
        assert loaded.name == "Test Blog"
        assert loaded.enabled is True
        assert loaded.error_count == 0

    engine.dispose()


def test_item_unique_url():
    engine = get_engine(":memory:")
    init_db(engine)

    session_cls = get_session(engine)
    with session_cls() as session:
        src = Source(name="Test", url="https://x.com/rss", enabled=True)
        session.add(src)
        session.flush()

        now = datetime.now(timezone.utc)
        item1 = Item(
            source_id=src.id,
            title="Hello",
            url="https://x.com/article/1",
            fetched_at=now,
        )
        session.add(item1)
        session.commit()

        item2 = Item(
            source_id=src.id,
            title="Hello Dup",
            url="https://x.com/article/1",
            fetched_at=now,
        )
        session.add(item2)
        import sqlalchemy.exc
        try:
            session.commit()
            assert False, "Should have raised IntegrityError"
        except sqlalchemy.exc.IntegrityError:
            session.rollback()

    engine.dispose()


def test_source_default_error_count():
    engine = get_engine(":memory:")
    init_db(engine)

    session_cls = get_session(engine)
    with session_cls() as session:
        src = Source(name="X", url="http://a.com", enabled=True)
        session.add(src)
        session.commit()
        assert session.get(Source, src.id).error_count == 0

    engine.dispose()
