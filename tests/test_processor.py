from unittest.mock import patch, MagicMock
from app.processor import process_item


@patch("app.processor.litellm.completion")
def test_process_item_returns_structured_result(mock_completion):
    mock_completion.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content='{"title_cn": "中文标题", "summary": "摘要内容", "category": "模型发布", "score": 85, "relevant": true}'
                )
            )
        ]
    )

    entry = {
        "title": "OpenAI releases GPT-5",
        "url": "https://openai.com/blog/gpt5",
        "summary": "OpenAI announced GPT-5 today.",
    }
    llm_config = {
        "provider": "openai",
        "api_key": "sk-test",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    }
    preferences = {
        "description": "关注 AI 领域",
        "categories": ["模型发布", "产品更新", "行业动态", "论文研究", "技术教程"],
    }

    result = process_item(entry, llm_config, preferences)
    assert result is not None
    assert result["title_cn"] == "中文标题"
    assert result["summary"] == "摘要内容"
    assert result["category"] == "模型发布"
    assert result["score"] == 85
    assert result["relevant"] is True


@patch("app.processor.litellm.completion")
def test_process_item_handles_llm_error(mock_completion):
    mock_completion.side_effect = Exception("API error")

    entry = {"title": "Test", "url": "http://x.com", "summary": ""}
    llm_config = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"}
    preferences = {"description": "AI", "categories": ["技术"]}

    result = process_item(entry, llm_config, preferences)
    assert result is None


@patch("app.processor.litellm.completion")
def test_process_item_handles_bad_json(mock_completion):
    mock_completion.return_value = MagicMock(
        choices=[
            MagicMock(message=MagicMock(content="not valid json {{{"))
        ]
    )

    entry = {"title": "Test", "url": "http://x.com", "summary": ""}
    llm_config = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"}
    preferences = {"description": "AI", "categories": ["技术"]}

    result = process_item(entry, llm_config, preferences)
    assert result is None


@patch("app.processor.litellm.completion")
def test_process_item_sends_correct_prompt(mock_completion):
    mock_completion.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content='{"title_cn": "t", "summary": "s", "category": "模型发布", "score": 50, "relevant": true}'
                )
            )
        ]
    )

    entry = {
        "title": "GPT-5 Released",
        "url": "https://example.com",
        "summary": "OpenAI announced GPT-5",
    }
    llm_config = {
        "provider": "openai",
        "api_key": "sk-test",
        "model": "gpt-4",
    }
    preferences = {
        "description": "关注 AI 领域前沿技术",
        "categories": ["模型发布", "技术教程"],
    }

    process_item(entry, llm_config, preferences)

    call_args = mock_completion.call_args
    messages = call_args[1]["messages"]
    assert len(messages) >= 1
    content = messages[0]["content"] if len(messages) == 1 else messages[1]["content"]
    assert "GPT-5 Released" in content
    assert "OpenAI announced" in content
    assert "模型发布" in content
    assert "技术教程" in content
    assert "关注 AI 领域前沿技术" in content


@patch("app.processor.litellm.completion")
def test_process_item_retries_on_bad_json(mock_completion):
    valid = '{"title_cn": "t", "summary": "s", "category": "模型发布", "score": 50, "relevant": true}'
    bad = "not json at all {{{"
    mock_completion.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=bad))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=valid))]),
    ]

    entry = {"title": "Test", "url": "http://x.com", "summary": ""}
    llm_config = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4"}
    preferences = {"description": "AI", "categories": ["模型发布"]}

    result = process_item(entry, llm_config, preferences)
    assert result is not None
    assert result["title_cn"] == "t"
    assert result["category"] == "模型发布"
    assert mock_completion.call_count == 2
