from unittest.mock import patch, MagicMock
from app.fetcher import fetch_feed


def _make_mock_entry(title, link, summary="", published=None):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = summary
    if published:
        entry.published_parsed = published
    else:
        entry.published_parsed = None

    def _get(key, default=""):
        return {"title": title, "link": link, "summary": summary}.get(key, default)
    entry.get = _get
    return entry


@patch("app.fetcher.feedparser.parse")
def test_fetch_feed_returns_entries(mock_parse):
    mock_parse.return_value = MagicMock(
        bozo=0,
        entries=[
            _make_mock_entry("Title 1", "http://a.com/1", "Summary 1"),
            _make_mock_entry("Title 2", "http://a.com/2", "Summary 2"),
        ],
    )
    result = fetch_feed("http://example.com/rss")
    assert len(result) == 2
    assert result[0]["title"] == "Title 1"
    assert result[0]["url"] == "http://a.com/1"
    assert result[0]["summary"] == "Summary 1"
    assert result[0]["published_at"] is None


@patch("app.fetcher.feedparser.parse")
def test_fetch_feed_respects_max_items(mock_parse):
    mock_parse.return_value = MagicMock(
        bozo=0,
        entries=[_make_mock_entry(f"T{i}", f"http://x.com/{i}") for i in range(30)],
    )
    result = fetch_feed("http://example.com/rss", max_items=10)
    assert len(result) == 10


@patch("app.fetcher.feedparser.parse")
def test_fetch_feed_handles_bozo(mock_parse):
    mock_parse.return_value = MagicMock(bozo=1, bozo_exception=ValueError("bad xml"), entries=[])
    result = fetch_feed("http://example.com/bad")
    assert result == []


@patch("app.fetcher.feedparser.parse")
def test_fetch_feed_handles_exception(mock_parse):
    mock_parse.side_effect = Exception("network error")
    result = fetch_feed("http://down.example.com/rss")
    assert result == []


@patch("app.fetcher.feedparser.parse")
def test_fetch_feed_extracts_published_date(mock_parse):
    mock_parse.return_value = MagicMock(
        bozo=0,
        entries=[
            _make_mock_entry("T1", "http://x.com/1", published=(2026, 6, 23, 10, 0, 0, 0, 175, 0)),
        ],
    )
    result = fetch_feed("http://x.com/rss")
    assert result[0]["published_at"] is not None
    assert "2026-06-23" in result[0]["published_at"]
