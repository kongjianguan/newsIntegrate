import json
import logging
import re

import litellm

logger = logging.getLogger(__name__)

# 系统提示词模板，指导 LLM 对 RSS 条目进行翻译、摘要、分类、评分和相关性判断
_PROMPT_TEMPLATE = """你是一个内容聚合助手。请处理以下 RSS 条目：

## 内容偏好
{preferences_description}

## 可用分类
{preferences_categories}

## 重要：你必须从上述"可用分类"列表中精确选择一个，不能修改名称、不能创建新分类、不能使用同义词或变体。如果没有任何分类匹配，请选择最接近的一个。

## RSS 条目
- 来源: {source_name}
- 原标题: {title}
- 原文摘要: {summary}

## 任务
1. 将原标题翻译为简洁中文
2. 生成 100-200 字中文摘要（基于原标题和原文摘要）
3. 判断是否与用户偏好相关（relevant: true/false）
4. 从可用分类中精确选择一个最合适的分类
5. 给出相关性评分（0-100，90+ 表示非常重要）

请**只输出**以下 JSON 格式，不要包含任何其他文字：
```json
{{
  "title_cn": "中文标题",
  "summary": "中文摘要",
  "category": "分类名",
  "score": 85,
  "relevant": true
}}
```"""


def _extract_json(text: str) -> dict | None:
    """尝试从 LLM 输出中提取 JSON，支持三种格式回退"""
    # 策略一：直接解析纯 JSON 文本
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 策略二：从 ```json ... ``` 代码块中提取
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 策略三：从文本中找到第一个 { ... } 结构
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _call_llm(llm_config: dict, messages: list) -> str | None:
    """调用 LLM 并返回响应文本，异常时返回 None"""
    try:
        response = litellm.completion(
            # 使用 "provider/model" 格式自动选择对应的 API 客户端
            model=f"{llm_config['provider']}/{llm_config['model']}",
            api_key=llm_config.get("api_key"),
            api_base=llm_config.get("base_url"),
            messages=messages,
            # 低温度保证输出的一致性和确定性
            temperature=0.3,
            max_tokens=500,
        )
        content = response.choices[0].message.content
        return content if content else None
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return None


def _normalize_category(category: str, valid_categories: list[str]) -> str:
    """将 LLM 输出的分类名映射到最接近的可用分类"""
    if category in valid_categories:
        return category
    for vc in valid_categories:
        if vc in category or category in vc:
            return vc
    return valid_categories[0] if valid_categories else category


def process_item(entry: dict, llm_config: dict, preferences: dict) -> dict | None:
    """调用 LLM 处理单条 RSS 条目，JSON 解析失败自动重试一次"""
    categories = preferences.get("categories", [])
    prompt = _PROMPT_TEMPLATE.format(
        preferences_description=preferences.get("description", ""),
        preferences_categories="\n".join(f"- {c}" for c in categories),
        source_name=entry.get("source_name", ""),
        title=entry.get("title", ""),
        summary=entry.get("summary", "") or "(无)",
    )

    content = _call_llm(llm_config, [{"role": "user", "content": prompt}])
    if content is None:
        return None
    result = _extract_json(content)
    if result is not None:
        if "category" in result:
            result["category"] = _normalize_category(result["category"], categories)
        return result

    # 首次解析失败时，将 LLM 的错误输出作为上下文再次请求，要求重新输出合法 JSON
    retry_prompt = "上次输出不是合法的 JSON 格式。请只输出 JSON，不要包含任何其他文字。"
    content = _call_llm(llm_config, [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": content},
        {"role": "user", "content": retry_prompt},
    ])
    if content is None:
        return None
    result = _extract_json(content)
    if result is not None and "category" in result:
        result["category"] = _normalize_category(result["category"], categories)
    return result
