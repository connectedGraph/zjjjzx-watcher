from __future__ import annotations

import json
import os
import re
import tomllib
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError


DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


def evaluate(url: str, api_key_env: str, timeout: float, conditions: str, listing_text: str) -> dict:
    if url:
        payload = {"conditions": conditions, "listing": listing_text}
        result = _post_json(url, payload, None, timeout)
    else:
        result = _evaluate_with_deepseek(api_key_env, timeout, conditions, listing_text)
    return _normalise_result(result)


def _evaluate_with_deepseek(
    api_key_env: str,
    timeout: float,
    conditions: str,
    listing_text: str,
) -> dict:
    settings = _load_deepseek_settings()
    api_key = os.getenv(api_key_env) or settings.get("api_key")
    if not api_key:
        raise RuntimeError(f"missing DeepSeek API key: set {api_key_env} or configure ~/.deepseek/config.toml")
    base_url = os.getenv("DEEPSEEK_BASE_URL") or settings.get("base_url") or DEEPSEEK_DEFAULT_BASE_URL
    model = os.getenv("DEEPSEEK_MODEL") or settings.get("model") or DEEPSEEK_DEFAULT_MODEL
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是家教需求匹配器。只能依据用户条件和家教条目判断。"
                    "必须返回单个 JSON 对象，不要 Markdown，不要额外文字。"
                    "JSON 字段必须为 pass(boolean)、reason(string)、extracted(object)。"
                    "extracted 必须包含 subject、grade、grade_rank、student_gender、"
                    "hourly_rate_min、hourly_rate_max、total_income、schedule_text、mode；"
                    "hourly_rate 表示按小时价格；若原文按次且有课时，换算为每小时。"
                    "total_income 表示该单预计总收入，无法确定时为 null；schedule_text 保留时间原文。"
                    "grade_rank 按小学1-6、初中7-9、高中10-12填写，无法确定为0。"
                    "无法确定的数值使用 null，文本使用空字符串。"
                ),
            },
            {
                "role": "user",
                "content": f"用户条件：\n{conditions}\n\n家教条目：\n{listing_text}",
            },
        ],
    }
    response = _post_json(f"{base_url.rstrip('/')}/chat/completions", payload, api_key, timeout)
    if not isinstance(response, dict):
        raise RuntimeError("DeepSeek response is not an object")
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("DeepSeek response has no assistant content") from error
    if not isinstance(content, str):
        raise RuntimeError("DeepSeek assistant content is not text")
    return _parse_json_content(content)


def _load_deepseek_settings() -> dict:
    path = Path.home() / ".deepseek" / "config.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as stream:
            settings = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError(f"cannot read {path}: {error}") from error
    return settings if isinstance(settings, dict) else {}


def _post_json(
    url: str,
    payload: dict,
    api_key: str | None,
    timeout: float,
) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"semantic API request failed: {error}") from error
    if not isinstance(result, dict):
        raise RuntimeError("semantic API response is not an object")
    return result


def _parse_json_content(content: str) -> dict:
    candidate = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            raise RuntimeError("DeepSeek did not return valid JSON")
        try:
            result = json.loads(match.group())
        except json.JSONDecodeError as error:
            raise RuntimeError("DeepSeek did not return valid JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError("semantic result is not an object")
    return result


def _normalise_result(result: dict) -> dict:
    if not isinstance(result.get("pass"), bool):
        raise RuntimeError("semantic API must return an object with boolean 'pass'")
    extracted = result.get("extracted", {})
    if not isinstance(extracted, dict):
        raise RuntimeError("semantic API field 'extracted' must be an object")
    return {"pass": result["pass"], "reason": str(result.get("reason", "")), "extracted": extracted}
