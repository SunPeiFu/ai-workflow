from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
HISTORY_PATH = Path("uploads/ai-copy-history.json")
PROVIDER_URLS = {
    "gemini": "https://gemini.google.com/app",
    "chatgpt": "https://chatgpt.com/",
}
TASK_NAMES = {
    "title": "标题优化",
    "body": "正文改写",
    "tags": "标签生成",
    "xiaohongshu": "小红书平台改写",
    "douyin": "抖音平台改写",
}
STRENGTH_NAMES = {
    "light": "轻度改写：保留原有结构，主要优化措辞和语句流畅度",
    "standard": "标准改写：调整结构、信息顺序和表达节奏",
    "deep": "深度改写：重组表达结构和叙述顺序，但保持事实、对象、立场和主旨不变",
}


def build_ai_copy_prompt(
    text: str,
    task: str = "body",
    strength: str = "standard",
    allow_emoji: bool = False,
    candidate_count: int = 3,
) -> str:
    source = str(text or "").strip()
    if not source:
        raise ValueError("请先输入需要处理的原始文案")
    task = task if task in TASK_NAMES else "body"
    strength = strength if strength in STRENGTH_NAMES else "standard"
    candidate_count = max(1, min(int(candidate_count or 3), 5))
    task_rule = {
        "title": "标题不要包含 #，保持核心事件与对象，避免夸张和标题党。",
        "body": "正文保留重要信息，使用自然段和真实口语表达，不要包含标签。",
        "tags": "每个标签必须以 # 开头，围绕原主题扩展，标签之间使用空格。",
        "xiaohongshu": "按小红书图文风格组织，体验表达自然、分段清晰，避免虚假种草。",
        "douyin": "按抖音图文风格组织，标题短而直接，正文紧凑，标签控制在 3-5 个。",
    }[task]
    emoji_rule = (
        "可以使用少量与原文语义一致的自然 emoji，不要堆砌。"
        if allow_emoji
        else "不要新增 emoji；原文已有 emoji 时可自然保留。"
    )
    return (
        "你是中文社交平台原创文案编辑。\n"
        f"任务：{TASK_NAMES[task]}。\n"
        f"改写强度：{STRENGTH_NAMES[strength]}。\n"
        f"要求生成 {candidate_count} 个候选。\n"
        "必须保持原文事实、对象、立场和核心主旨，不得编造商品参数、体验、功效、价格或促销信息。\n"
        "通过结构、措辞、节奏、信息顺序和口语表达提升原创度与可读性。\n"
        "避免绝对化、医疗功效、虚假承诺和明显 AI 套话。\n"
        f"{task_rule}\n"
        f"{emoji_rule}\n"
        "只返回一个 JSON 数组，数组元素必须是完整候选字符串；不要 Markdown，不要解释，不要输出思考过程。\n\n"
        f"原文：\n{source}"
    )


def parse_ai_copy_candidates(text: str, candidate_count: int = 3) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        first_array = _first_json_array(cleaned)
        if first_array:
            try:
                parsed = json.loads(first_array)
            except json.JSONDecodeError:
                parsed = None
    if isinstance(parsed, dict):
        parsed = parsed.get("suggestions") or parsed.get("items") or parsed.get("data")
    if isinstance(parsed, list):
        candidates = [_candidate_text(item) for item in parsed]
    else:
        numbered = []
        for line in cleaned.splitlines():
            match = re.match(r"^\s*(?:\d+[.、)]|[-*])\s*(.+?)\s*$", line)
            if match:
                numbered.append(match.group(1).strip())
        candidates = numbered or [cleaned]
    result = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in result:
            result.append(candidate)
    limit = max(1, min(int(candidate_count or 3), 5))
    return result[:limit]


def generate_ai_copy_with_lmstudio(payload: dict[str, Any], curl_path: str | None = None) -> dict[str, Any]:
    task = str(payload.get("task") or "body")
    prompt = build_ai_copy_prompt(
        payload.get("text", ""),
        task=task,
        strength=str(payload.get("strength") or "standard"),
        allow_emoji=bool(payload.get("allow_emoji")),
        candidate_count=int(payload.get("candidate_count") or 3),
    )
    base_url = str(payload.get("base_url") or LMSTUDIO_BASE_URL).rstrip("/")
    model = str(payload.get("model") or "").strip() or _default_lmstudio_model(base_url)
    if not model:
        raise RuntimeError("LM Studio 当前没有可用模型，请先在 LM Studio 中加载模型")
    candidate_count = max(1, min(int(payload.get("candidate_count") or 3), 5))
    request_payload = {
        "model": model,
        "temperature": 0.75,
        "max_tokens": _max_output_tokens(task, candidate_count),
        "stop": ["<|user|>", "<|assistant|>"],
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "system",
                "content": "你是中文社交平台文案助手，只输出用户要求的 JSON 数组。",
            },
            {"role": "user", "content": f"{prompt}\n\n/no_think"},
        ],
    }
    resolved_curl = curl_path or shutil.which("curl")
    if resolved_curl:
        data = _curl_json_request(f"{base_url}/chat/completions", request_payload, resolved_curl)
        transport = "curl"
    else:
        data = _http_json_request(f"{base_url}/chat/completions", request_payload)
        transport = "python-http"
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    suggestions = parse_ai_copy_candidates(content, candidate_count)
    if not suggestions:
        raise RuntimeError("本地模型没有返回可用文案，请调整原文或切换模型后重试")
    return {
        "ok": True,
        "provider": "lmstudio",
        "model": model,
        "prompt": prompt,
        "suggestions": suggestions,
        "raw": content,
        "transport": transport,
    }


def web_ai_copy_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in PROVIDER_URLS:
        raise ValueError("网页 AI 类型仅支持 Gemini 或 ChatGPT")
    prompt = build_ai_copy_prompt(
        payload.get("text", ""),
        task=str(payload.get("task") or "body"),
        strength=str(payload.get("strength") or "standard"),
        allow_emoji=bool(payload.get("allow_emoji")),
        candidate_count=int(payload.get("candidate_count") or 3),
    )
    return {"ok": True, "provider": provider, "url": PROVIDER_URLS[provider], "prompt": prompt}


def list_ai_copy_history(root: Path) -> dict[str, Any]:
    items = _load_history(root)
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {"ok": True, "items": items}


def save_ai_copy_history(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    items = _load_history(root)
    now = _now()
    entry_id = str(payload.get("id") or "").strip() or _history_id(payload, now)
    item = {
        "id": entry_id,
        "provider": str(payload.get("provider") or "lmstudio"),
        "model": str(payload.get("model") or ""),
        "task": str(payload.get("task") or "body"),
        "strength": str(payload.get("strength") or "standard"),
        "allow_emoji": bool(payload.get("allow_emoji")),
        "source_text": str(payload.get("source_text") or payload.get("text") or ""),
        "prompt": str(payload.get("prompt") or ""),
        "suggestions": [str(value) for value in payload.get("suggestions") or [] if str(value).strip()],
        "selected_text": str(payload.get("selected_text") or ""),
        "pipeline_item_id": str(payload.get("pipeline_item_id") or ""),
        "created_at": now,
        "updated_at": now,
    }
    existing = next((entry for entry in items if entry.get("id") == entry_id), None)
    if existing:
        item["created_at"] = existing.get("created_at") or now
        items = [item if entry.get("id") == entry_id else entry for entry in items]
    else:
        items.append(item)
    _save_history(root, items)
    return {"ok": True, "item": item}


def delete_ai_copy_history(root: Path, entry_id: str) -> dict[str, Any]:
    items = _load_history(root)
    remaining = [item for item in items if item.get("id") != entry_id]
    deleted = len(items) - len(remaining)
    _save_history(root, remaining)
    return {"ok": True, "deleted": deleted}


def _curl_json_request(url: str, payload: dict[str, Any], curl_path: str) -> dict[str, Any]:
    command = [
        curl_path,
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "180",
        "-H",
        "Content-Type: application/json",
        "-H",
        "Authorization: Bearer lm-studio",
        "--data-binary",
        "@-",
        url,
    ]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=190,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("LM Studio 请求超过 180 秒，请减少原文长度或切换更快模型") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"调用本地 LM Studio 失败：{message[:500] or 'curl 执行失败'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LM Studio 返回了无法解析的 JSON") from exc


def _http_json_request(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port or 80, timeout=180)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        connection.request(
            "POST",
            parsed.path,
            body=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"},
        )
        response = connection.getresponse()
        text = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"无法连接 LM Studio：{exc}") from exc
    finally:
        connection.close()
    if response.status >= 400:
        raise RuntimeError(f"LM Studio HTTP {response.status}：{text[:500]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LM Studio 返回了无法解析的 JSON") from exc


def _default_lmstudio_model(base_url: str) -> str:
    try:
        parsed = urlparse(f"{base_url}/models")
        connection = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port or 80, timeout=5)
        connection.request("GET", parsed.path, headers={"Authorization": "Bearer lm-studio"})
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
    except (OSError, json.JSONDecodeError):
        return ""
    for item in data.get("data") or []:
        model_id = str(item.get("id") or "").strip()
        if model_id and "embedding" not in model_id.lower():
            return model_id
    return ""


def _candidate_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("content") or item.get("value") or "")
    return str(item)


def _max_output_tokens(task: str, candidate_count: int) -> int:
    per_candidate = {
        "title": 200,
        "tags": 260,
        "body": 700,
        "xiaohongshu": 820,
        "douyin": 600,
    }.get(task, 700)
    return min(4500, 1800 + per_candidate * candidate_count)


def _first_json_array(text: str) -> str:
    start = text.find("[")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _load_history(root: Path) -> list[dict[str, Any]]:
    path = root / HISTORY_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []


def _save_history(root: Path, items: list[dict[str, Any]]) -> None:
    path = root / HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _history_id(payload: dict[str, Any], now: str) -> str:
    source = f"{now}|{payload.get('provider')}|{payload.get('task')}|{payload.get('source_text') or payload.get('text')}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
