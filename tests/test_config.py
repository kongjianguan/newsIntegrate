import os
import tempfile
from app.config import load_config, save_config


def test_load_config_parses_env_vars():
    yaml_content = """
llm:
  api_key: "${TEST_API_KEY}"
  model: gpt-4o-mini
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        path = f.name

    os.environ["TEST_API_KEY"] = "sk-test-123"
    try:
        config = load_config(path)
        assert config["llm"]["api_key"] == "sk-test-123"
        assert config["llm"]["model"] == "gpt-4o-mini"
    finally:
        os.unlink(path)
        del os.environ["TEST_API_KEY"]


def test_load_config_keeps_literal_values():
    yaml_content = """
server:
  port: 8765
sources:
  - name: Test
    url: https://example.com/rss
    enabled: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        path = f.name

    try:
        config = load_config(path)
        assert config["server"]["port"] == 8765
        assert config["sources"][0]["name"] == "Test"
        assert config["sources"][0]["enabled"] is True
    finally:
        os.unlink(path)


def test_save_config_roundtrip():
    config = {
        "llm": {"model": "gpt-4o", "api_key": "sk-key"},
        "server": {"port": 9999},
        "sources": [{"name": "S1", "url": "http://a.com", "enabled": True}],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name

    try:
        save_config(config, path)
        loaded = load_config(path)
        assert loaded["llm"]["model"] == "gpt-4o"
        assert loaded["server"]["port"] == 9999
        assert loaded["sources"][0]["name"] == "S1"
    finally:
        os.unlink(path)


def test_load_config_file_not_found():
    config = load_config("/nonexistent/path.yaml")
    assert config == {}
