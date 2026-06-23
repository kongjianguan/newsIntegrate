import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
from time import mktime

import feedparser

# RSS 中常见的日期格式列表，按优先级排列，依次尝试解析
_DATE_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
]


def _extract_year_from_entry(entry: dict) -> int | None:
    """当 RSS item 无日期时, 从 dc:source 或 DOI 中提取年份"""
    # 尝试从 dc:source 字段提取四位年份
    source = entry.get("dc_source", "")
    if source:
        m = re.search(r"\b(20\d{2})\b", source)
        if m:
            return int(m.group(1))
    # 尝试从 DOI 编号末尾提取年份（DOI 通常以年份开头后接流水号）
    doi = entry.get("prism_doi") or entry.get("dc_identifier", "")
    if doi.startswith("doi:"):
        doi = doi[4:]
    if doi:
        m = re.search(r"(20\d{2})\d{4}$", doi)
        if m:
            return int(m.group(1))
    return None


def _parse_date(raw: str | None, parsed) -> str | None:
    """将 RSS 条目的原始日期值解析为 ISO 格式字符串，优先尝试文本格式，回退到 feedparser 解析后的 struct_time"""
    # 优先尝试用多种文本格式模板解析日期字符串
    if raw:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
    # 如果文本解析失败，使用 feedparser 已解析的 struct_time 元组
    if parsed and isinstance(parsed, tuple) and len(parsed) >= 6:
        try:
            return datetime.fromtimestamp(
                mktime(parsed), tz=timezone.utc
            ).isoformat()
        except Exception:
            pass
    return None


def fetch_feed(url: str, max_items: int = 20) -> list[dict]:
    """抓取 RSS/Atom 订阅源，返回最多 max_items 条标准化条目"""
    parsed = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(feedparser.parse, url)
        try:
            parsed = future.result(timeout=20)
        except TimeoutError:
            return []
        except Exception:
            return []

    if parsed.bozo and not parsed.entries:
        return []

    results = []
    for entry in parsed.entries[:max_items]:
        # 从多种可能的日期字段中提取发布日期
        published_at = _parse_date(
            entry.get("published") or entry.get("pubDate") or entry.get("updated"),
            getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None),
        )
        # 如果完全无法解析日期，尝试从元数据中提取年份，默认使用该年 1 月 1 日
        if not published_at:
            year = _extract_year_from_entry(entry)
            if year:
                published_at = datetime(year, 1, 1, tzinfo=timezone.utc).isoformat()

        results.append({
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", "").strip(),
            "summary": entry.get("summary", "").strip(),
            "published_at": published_at,
        })

    return results
