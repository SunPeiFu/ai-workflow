from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


STATE_RELATIVE_PATH = Path("uploads/content-pipeline.json")
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
TRAILING_URL_PUNCTUATION = "，。！？；：、,.!?;:)]}）】》\"'"
RISKY_TERMS = ("全网最好", "绝对", "保证", "治疗", "治愈", "100%", "零风险", "永久有效")


def add_pool_links(root: Path, text: str) -> dict[str, Any]:
    state = _load_state(root)
    urls = _extract_urls(text)
    added_items = []
    for url in urls:
        item_id = _item_id(url)
        if item_id in state["items"]:
            continue
        now = _now()
        item = _default_item(item_id, url, now)
        state["items"][item_id] = item
        added_items.append(item)
    _save_state(root, state)
    return {"ok": True, "added": len(added_items), "items": added_items}


def list_pool_items(root: Path) -> dict[str, Any]:
    state = _load_state(root)
    changed = _merge_existing_packages(root, state)
    if changed:
        _save_state(root, state)
    items = sorted(state["items"].values(), key=lambda item: item.get("updated_at", ""), reverse=True)
    for item in items:
        item["image_count"] = len(item.get("images") or [])
    return {"ok": True, "items": items}


def update_pool_item(root: Path, item_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    state = _load_state(root)
    item = state["items"].get(item_id)
    if not item:
        raise KeyError(f"素材不存在: {item_id}")
    allowed = {
        "title",
        "body",
        "tags",
        "images",
        "cover_image",
        "status",
        "product",
        "drafts",
        "audit",
    }
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key == "tags":
            value = _tag_list(value)
        if key == "images":
            value = _image_list(value)
        item[key] = value
    item["updated_at"] = _now()
    _save_state(root, state)
    return item


def score_product(product: dict[str, Any]) -> dict[str, Any]:
    commission = _clamp(_number(product.get("commission_rate")) / 30 * 20, 0, 20)
    demand = _clamp(math.log10(max(_number(product.get("monthly_sales")), 1)) / 4 * 15, 0, 15)
    rating = _clamp((_number(product.get("rating")) - 4) / 1 * 15, 0, 15)
    store = _clamp((_number(product.get("store_score")) - 4) / 1 * 10, 0, 10)
    refund = _clamp((20 - _number(product.get("refund_rate"))) / 20 * 15, 0, 15)
    coupon = 5 if product.get("has_coupon") else 0
    assets = _clamp(_number(product.get("asset_completeness")) / 100 * 20, 0, 20)
    breakdown = {
        "commission": round(commission, 1),
        "demand": round(demand, 1),
        "rating": round(rating, 1),
        "store": round(store, 1),
        "refund": round(refund, 1),
        "coupon": coupon,
        "assets": round(assets, 1),
    }
    score = round(sum(breakdown.values()))
    if score >= 75:
        grade = "优先测试"
    elif score >= 60:
        grade = "可小量测试"
    else:
        grade = "暂缓"
    return {"score": score, "grade": grade, "breakdown": breakdown}


def update_product_score(root: Path, item_id: str, product: dict[str, Any]) -> dict[str, Any]:
    result = score_product(product)
    item = update_pool_item(
        root,
        item_id,
        {"product": product, "status": "scored"},
    )
    state = _load_state(root)
    state["items"][item_id]["product_score"] = result
    state["items"][item_id]["updated_at"] = _now()
    _save_state(root, state)
    item = state["items"][item_id]
    return {"ok": True, "item": item, **result}


def batch_rewrite_items(root: Path, item_ids: list[str], level: str = "standard") -> dict[str, Any]:
    state = _load_state(root)
    rewritten = []
    for item_id in item_ids:
        item = state["items"].get(item_id)
        if not item:
            continue
        item["drafts"] = _platform_drafts(item, level)
        item["status"] = "rewritten"
        item["updated_at"] = _now()
        rewritten.append(item)
    _save_state(root, state)
    return {"ok": True, "items": rewritten}


def update_image_arrangement(
    root: Path,
    item_id: str,
    ordered_images: list[Any],
    cover_image: Any | None,
) -> dict[str, Any]:
    state = _load_state(root)
    item = state["items"].get(item_id)
    if not item:
        raise KeyError(f"素材不存在: {item_id}")
    known = {_image_key(image): image for image in item.get("images") or []}
    images = []
    for candidate in ordered_images:
        key = _image_key(candidate)
        if key in known and all(_image_key(existing) != key for existing in images):
            images.append(known[key])
    cover_key = _image_key(cover_image) if cover_image else ""
    item["images"] = images
    item["cover_image"] = known.get(cover_key) if cover_key in {_image_key(image) for image in images} else None
    item["status"] = "arranged"
    item["updated_at"] = _now()
    _save_state(root, state)
    return item


def audit_pool_item(root: Path, item_id: str) -> dict[str, Any]:
    state = _load_state(root)
    item = state["items"].get(item_id)
    if not item:
        raise KeyError(f"素材不存在: {item_id}")
    issues: list[dict[str, str]] = []
    score = 100
    text = f"{item.get('title', '')} {item.get('body', '')}"
    matched_terms = [term for term in RISKY_TERMS if term.lower() in text.lower()]
    if matched_terms:
        issues.append(
            {
                "severity": "blocker",
                "field": "copy",
                "message": f"包含高风险绝对化或功效词：{'、'.join(matched_terms)}",
            }
        )
        score -= 45
    images = item.get("images") or []
    if not images:
        issues.append({"severity": "blocker", "field": "images", "message": "缺少发布图片"})
        score -= 30
    elif not item.get("cover_image"):
        issues.append({"severity": "warning", "field": "cover", "message": "尚未指定封面图"})
        score -= 8
    product = item.get("product") or {}
    missing_product = [key for key in ("name", "price", "commission_rate", "rating") if product.get(key) in (None, "")]
    if missing_product:
        issues.append(
            {
                "severity": "warning",
                "field": "product",
                "message": f"商品信息不完整：{', '.join(missing_product)}",
            }
        )
        score -= min(20, len(missing_product) * 5)
    if not str(item.get("title") or "").strip():
        issues.append({"severity": "blocker", "field": "title", "message": "标题为空"})
        score -= 25
    if not str(item.get("body") or "").strip():
        issues.append({"severity": "blocker", "field": "body", "message": "正文为空"})
        score -= 20
    score = max(0, score)
    ready = score >= 70 and not any(issue["severity"] == "blocker" for issue in issues)
    result = {"score": score, "ready_to_publish": ready, "issues": issues}
    item["audit"] = result
    item["status"] = "ready" if ready else "blocked"
    item["updated_at"] = _now()
    _save_state(root, state)
    return result


def _default_item(item_id: str, url: str, now: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "url": url,
        "platform": _platform(url),
        "title": "",
        "body": "",
        "tags": [],
        "images": [],
        "cover_image": None,
        "status": "pending",
        "product": {},
        "product_score": None,
        "drafts": {},
        "audit": None,
        "created_at": now,
        "updated_at": now,
    }


def _load_state(root: Path) -> dict[str, Any]:
    path = root / STATE_RELATIVE_PATH
    if not path.exists():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "items": {}}
    items = data.get("items") or {}
    if isinstance(items, list):
        items = {item["id"]: item for item in items if isinstance(item, dict) and item.get("id")}
    return {"version": 1, "items": items}


def _save_state(root: Path, state: dict[str, Any]) -> None:
    path = root / STATE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _merge_existing_packages(root: Path, state: dict[str, Any]) -> bool:
    changed = False
    package_root = root / "remix_packages"
    if not package_root.exists():
        return False
    for analysis_path in package_root.rglob("analysis.json"):
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        url = str(analysis.get("url") or "").strip()
        if not url:
            continue
        item_id = _item_id(url)
        copywriting = analysis.get("copywriting") or {}
        images = _image_list(analysis.get("images") or [])
        now = _now()
        existing = state["items"].get(item_id)
        if existing:
            if existing.get("status") != "pending":
                continue
            item = existing
        else:
            item = _default_item(item_id, url, now)
            state["items"][item_id] = item
        item.update(
            {
                "platform": analysis.get("platform") or item["platform"],
                "title": copywriting.get("title") or item.get("title", ""),
                "body": copywriting.get("body") or item.get("body", ""),
                "tags": _tag_list(copywriting.get("tags") or item.get("tags", [])),
                "images": images or item.get("images", []),
                "status": "analyzed",
                "source_package": str(analysis_path.parent),
                "updated_at": now,
            }
        )
        changed = True
    return changed


def _platform_drafts(item: dict[str, Any], level: str) -> dict[str, dict[str, str]]:
    title = str(item.get("title") or "值得关注的实用好物").strip()
    body = str(item.get("body") or "").strip()
    tags = _tag_list(item.get("tags") or [])
    xhs_title = _trim(f"{title}｜使用前先看这几点", 40)
    douyin_title = _trim(f"{title}，重点都整理好了", 30)
    if level == "deep":
        xhs_body = f"最近认真对比了这款产品，先说结论：{body} 我把适合人群、使用场景和选择时容易忽略的细节都整理在这里，按自己的实际需求判断会更稳妥。"
        douyin_body = f"{body} 选购时重点看使用场景、核心参数和真实需求，别只看宣传。"
    else:
        xhs_body = f"{body} 这篇把使用场景和选择重点一次讲清楚。"
        douyin_body = f"{body} 重点看需求、参数和实际使用场景。"
    base_tags = tags + ["好物分享", "选购指南", "实用分享"]
    return {
        "xiaohongshu": {
            "title": xhs_title,
            "body": xhs_body.strip(),
            "tags": " ".join(f"#{tag.lstrip('#')}" for tag in _unique(base_tags)[:8]),
        },
        "douyin": {
            "title": douyin_title,
            "body": _trim(douyin_body.strip(), 280),
            "tags": " ".join(f"#{tag.lstrip('#')}" for tag in _unique(base_tags)[:5]),
        },
    }


def _extract_urls(text: str) -> list[str]:
    return _unique(match.rstrip(TRAILING_URL_PUNCTUATION) for match in URL_PATTERN.findall(text or ""))


def _item_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "douyin" in host:
        return "douyin"
    if "xiaohongshu" in host or "xhslink" in host:
        return "xiaohongshu"
    if "kuaishou" in host:
        return "kuaishou"
    return "unknown"


def _tag_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\s,，]+", value)
    return _unique(str(item).strip().lstrip("#") for item in (value or []) if str(item).strip())


def _image_list(value: Any) -> list[Any]:
    result = []
    for image in value or []:
        normalized = image
        if isinstance(image, dict):
            normalized = image.get("path") or image.get("url") or image
        if normalized and _image_key(normalized) not in {_image_key(existing) for existing in result}:
            result.append(normalized)
    return result


def _image_key(image: Any) -> str:
    if isinstance(image, dict):
        return str(image.get("path") or image.get("url") or "")
    return str(image or "")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _trim(text: str, length: int) -> str:
    return text if len(text) <= length else text[: max(0, length - 1)].rstrip() + "…"


def _unique(values: Any) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
