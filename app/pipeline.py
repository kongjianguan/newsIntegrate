import threading
from datetime import datetime, timedelta, timezone

from app.database import get_engine, get_session, init_db
from app.fetcher import fetch_feed
from app.models import Item, Source
from app.processor import process_item

_pipeline_lock = threading.Lock()


def _parse_datetime(value: str | None) -> datetime | None:
    """将 ISO 格式字符串转为 offset-aware 的 datetime 对象"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def run_pipeline(db_path: str, config: dict) -> dict:
    """执行完整管线：遍历信源→抓取→去重→LLM处理→入库→清理旧数据"""
    if not _pipeline_lock.acquire(blocking=False):
        return {"fetched": 0, "new": 0, "errors": 0, "skipped": "already running"}

    stats = {"fetched": 0, "new": 0, "errors": 0}

    engine = get_engine(db_path)
    init_db(engine)
    session_cls = get_session(engine)

    llm_config = config.get("llm", {})
    preferences = config.get("preferences", {})
    retention_days = config.get("retention_days", 7)

    try:
        for source_conf in config.get("sources", []):
            if not source_conf.get("enabled", True):
                continue

            try:
                entries = fetch_feed(source_conf["url"])
                stats["fetched"] += len(entries)
            except Exception:
                stats["errors"] += 1
                with session_cls() as s:
                    src = s.query(Source).filter_by(url=source_conf["url"]).first()
                    if src:
                        src.error_count += 1
                        s.commit()
                continue

            with session_cls() as s:
                db_source = s.query(Source).filter_by(url=source_conf["url"]).first()
                if not db_source:
                    db_source = Source(
                        name=source_conf["name"],
                        url=source_conf["url"],
                        enabled=source_conf.get("enabled", True),
                    )
                    s.add(db_source)
                    s.flush()
                else:
                    db_source.name = source_conf["name"]
                    db_source.enabled = source_conf.get("enabled", True)

                for entry in entries:
                    url = entry.get("url", "")
                    if not url:
                        continue

                    existing = s.query(Item).filter_by(url=url).first()
                    if existing:
                        continue

                    entry_with_source = {**entry, "source_name": source_conf["name"]}
                    processed = process_item(entry_with_source, llm_config, preferences)

                    if processed is None:
                        item = Item(
                            source_id=db_source.id,
                            title=entry.get("title", ""),
                            title_cn=None,
                            url=url,
                            summary=None,
                            category=None,
                            score=None,
                            published_at=_parse_datetime(entry.get("published_at")),
                        )
                        s.add(item)
                        stats["new"] += 1
                        continue

                    if not processed.get("relevant", True):
                        continue

                    item = Item(
                        source_id=db_source.id,
                        title=entry.get("title", ""),
                        title_cn=processed.get("title_cn"),
                        url=url,
                        summary=processed.get("summary"),
                        category=processed.get("category"),
                        score=processed.get("score"),
                        published_at=_parse_datetime(entry.get("published_at")),
                    )
                    s.add(item)
                    stats["new"] += 1

                db_source.last_fetched_at = datetime.now(timezone.utc)
                db_source.error_count = 0
                s.commit()

        with session_cls() as s:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            s.query(Item).filter(Item.fetched_at < cutoff).delete()
            s.commit()

        return stats
    finally:
        engine.dispose()
        _pipeline_lock.release()
