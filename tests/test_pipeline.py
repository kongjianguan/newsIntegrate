from unittest.mock import patch, MagicMock
import tempfile
import os

from app.database import get_engine, init_db, get_session
from app.models import Source
from app.pipeline import run_pipeline


@patch("app.pipeline.process_item")
@patch("app.pipeline.fetch_feed")
def test_run_pipeline_fetches_and_saves(mock_fetch, mock_process):
    mock_fetch.return_value = [
        {"title": "New AI Model", "url": "https://example.com/1", "summary": "test", "published_at": None},
    ]
    mock_process.return_value = {
        "title_cn": "新AI模型",
        "summary": "摘要",
        "category": "模型发布",
        "score": 80,
        "relevant": True,
    }

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        engine = get_engine(db_path)
        init_db(engine)
        session_cls = get_session(engine)
        with session_cls() as s:
            s.add(Source(name="Test", url="http://x.com/rss", enabled=True))
            s.commit()

        config = {
            "llm": {"provider": "openai", "api_key": "sk", "model": "gpt"},
            "sources": [{"name": "Test", "url": "http://x.com/rss", "enabled": True}],
            "preferences": {"description": "AI", "categories": ["模型发布"]},
            "retention_days": 7,
        }

        result = run_pipeline(db_path, config)
        assert result["fetched"] == 1
        assert result["new"] == 1
        assert result["errors"] == 0

        engine.dispose()
    finally:
        os.unlink(db_path)


@patch("app.pipeline.fetch_feed")
def test_run_pipeline_skips_duplicate_urls(mock_fetch):
    mock_fetch.return_value = [
        {"title": "Same URL", "url": "https://example.com/dup", "summary": "", "published_at": None},
    ]

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        engine = get_engine(db_path)
        init_db(engine)
        session_cls = get_session(engine)
        with session_cls() as s:
            src = Source(name="Test", url="http://x.com/rss", enabled=True)
            s.add(src)
            s.commit()

        config = {
            "sources": [{"name": "Test", "url": "http://x.com/rss", "enabled": True}],
            "llm": {"provider": "openai", "api_key": "sk", "model": "gpt"},
            "preferences": {"description": "AI", "categories": ["模型发布"]},
            "retention_days": 7,
        }

        # First run: saves item (mock LLM to return None for simplicity)
        with patch("app.pipeline.process_item", return_value=None):
            run_pipeline(db_path, config)

        # Second run: same URL, should skip
        result = run_pipeline(db_path, config)
        assert result["new"] == 0

        engine.dispose()
    finally:
        os.unlink(db_path)


@patch("app.pipeline.fetch_feed")
def test_run_pipeline_handles_fetch_error(mock_fetch):
    mock_fetch.side_effect = Exception("network down")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        engine = get_engine(db_path)
        init_db(engine)
        session_cls = get_session(engine)
        with session_cls() as s:
            s.add(Source(name="Test", url="http://x.com/rss", enabled=True))
            s.commit()

        config = {
            "sources": [{"name": "Test", "url": "http://x.com/rss", "enabled": True}],
            "llm": {"provider": "openai", "api_key": "sk", "model": "gpt"},
            "preferences": {"description": "AI", "categories": ["模型发布"]},
            "retention_days": 7,
        }

        result = run_pipeline(db_path, config)
        assert result["errors"] >= 1
        assert result["fetched"] == 0

        # Verify error_count was incremented
        with session_cls() as s:
            src = s.query(Source).first()
            assert src.error_count == 1

        engine.dispose()
    finally:
        os.unlink(db_path)
