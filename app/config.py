import os
import re
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv()

# 匹配 ${VAR_NAME} 格式的环境变量引用模式
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value):
    """递归遍历整个配置结构，将字符串中的 ${ENV_VAR} 替换为实际环境变量值"""
    if isinstance(value, str):
        def replacer(m):
            return os.environ.get(m.group(1), "")
        return _ENV_VAR_RE.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def load_config(path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件，并解析其中的环境变量引用"""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    return _resolve_env(data)


def save_config(config: dict, path: str = "config.yaml") -> None:
    """保存配置字典为 YAML 文件"""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
