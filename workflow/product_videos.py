from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


PRODUCT_VIDEO_TYPES = ["商品种草", "商品测评", "避坑对比", "美食教程"]
PRODUCT_CATEGORIES = ["厨房清洁耗材", "调味品/酱料", "厨房用品", "小家电", "食材/半成品", "家居日用"]

RISK_TERMS = {
    "100%": "避免绝对化承诺，改成“多数场景下”“实测感觉”。",
    "永久": "避免永久性承诺，改成“日常使用更省心”。",
    "最强": "避免最高级，改成具体对比维度。",
    "第一": "避免排名承诺，除非有可公开核验的权威来源。",
    "无毒": "食品、清洁、厨具类不要直接承诺无毒，改成展示检测/材质信息并人工复核。",
    "排毒": "避免健康功效暗示，改成普通饮食或使用体验描述。",
    "根治": "不要承诺医疗效果。",
    "治愈": "不要承诺医疗或心理治疗效果。",
    "必瘦": "不要承诺身体结果。",
    "稳赚": "不要承诺收益结果。",
}


def normalize_product_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        "content_mode": str(payload.get("content_mode") or "product").strip() or "product",
        "video_type": str(payload.get("video_type") or "商品种草").strip() or "商品种草",
        "product_name": str(payload.get("product_name") or "").strip(),
        "product_category": str(payload.get("product_category") or "厨房用品").strip() or "厨房用品",
        "price": str(payload.get("price") or "").strip(),
        "commission": str(payload.get("commission") or "").strip(),
        "pain_point": str(payload.get("pain_point") or "").strip(),
        "selling_points": str(payload.get("selling_points") or "").strip(),
        "target_platform": str(payload.get("target_platform") or "douyin").strip() or "douyin",
        "product_link": str(payload.get("product_link") or "").strip(),
        "notes": str(payload.get("product_notes") or payload.get("notes") or "").strip(),
    }


def is_product_payload(payload: Dict[str, Any]) -> bool:
    return str(payload.get("content_mode") or "").strip() == "product" or bool(str(payload.get("product_name") or "").strip())


def product_video_script(payload: Dict[str, Any]) -> str:
    product = normalize_product_payload(payload)
    name = product["product_name"] or "这款商品"
    category = product["product_category"]
    video_type = product["video_type"]
    pain = product["pain_point"] or "日常使用里这个小问题很烦"
    selling_points = _split_points(product["selling_points"]) or ["使用更顺手", "场景更明确", "复购成本可控"]
    platform = product["target_platform"]
    price = product["price"] or "按当前页面价格为准"
    commission = product["commission"] or "待填写"

    platform_line = {
        "douyin": "节奏要快，前三秒先把痛点抛出来，别先讲参数。",
        "xiaohongshu": "表达要像真实体验，重点讲使用场景、细节和适合谁。",
        "bilibili": "信息量可以更足，适合做对比、避坑和长期使用感。",
    }.get(platform, "按目标平台调整节奏。")

    scene_line = _scene_line(category)
    points_text = "、".join(selling_points[:4])

    return (
        f"开头钩子：如果你也遇到过{pain}，先别急着换一堆东西。\n\n"
        f"场景画面：{scene_line}镜头给到真实使用环境，不要只拍商品包装。\n\n"
        f"商品出场：这期看的是{name}，属于{category}，更适合解决的就是刚才这个场景。\n\n"
        f"核心卖点：我会重点看三点，{points_text}。如果这三点不过关，再便宜也不建议冲。\n\n"
        f"使用过程：第一步先展示使用前的问题，第二步展示{name}实际怎么用，第三步拍使用后的对比结果。\n\n"
        f"价格理由：当前价格参考是{price}，佣金/利润备注是{commission}。拍摄时不要硬喊低价，要说清楚适合谁买、不适合谁买。\n\n"
        f"平台节奏：{platform_line}\n\n"
        f"结尾转化：想看同类{video_type}清单，可以在评论区留“厨房”，我会继续把好用和不好用的都测出来。"
    )


def product_asset_checklist(category: str) -> List[str]:
    base = [
        "商品主图",
        "商品包装/规格细节",
        "价格/优惠截图",
        "真实使用过程图",
        "使用后对比图",
        "用户评价截图",
    ]
    if "清洁" in category:
        return ["使用前油污/杂乱场景", *base, "清洁后台面/餐具对比"]
    if "调味" in category or "食材" in category:
        return ["成品美食图", *base, "配料表/营养成分截图"]
    if "小家电" in category:
        return ["厨房台面摆放图", *base, "噪音/容量/清洗细节图"]
    return base


def product_compliance_risks(text: str) -> List[Dict[str, str]]:
    risks = []
    for term, suggestion in RISK_TERMS.items():
        if term == "第一" and not re.search(r"(销量|排名|行业|全网|平台|同类|品类|效果|口碑|品牌)第一", text):
            continue
        position = text.find(term)
        if position >= 0:
            risks.append({"term": term, "level": "high", "suggestion": suggestion, "position": position})
    risks.sort(key=lambda item: item["position"])
    for risk in risks:
        risk.pop("position", None)
    return risks


def write_product_project_files(project_dir: Path, payload: Dict[str, Any], script_text: str) -> None:
    product = normalize_product_payload(payload)
    risks = product_compliance_risks(script_text + "\n" + json.dumps(product, ensure_ascii=False))
    checklist = product_asset_checklist(product["product_category"])

    (project_dir / "brief.md").write_text(product_brief_markdown(product), encoding="utf-8")
    (project_dir / "assets" / "product-shot-list.md").write_text(
        "# 商品素材清单\n\n" + "\n".join(f"- {item}" for item in checklist) + "\n",
        encoding="utf-8",
    )
    (project_dir / "exports" / "compliance-risks.json").write_text(
        json.dumps({"ok": True, "risks": risks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project_dir / "episode.yaml").write_text(
        (project_dir / "episode.yaml").read_text(encoding="utf-8")
        + "content_mode: product\n"
        + f"video_type: {product['video_type']}\n"
        + f"product_name: {product['product_name']}\n"
        + f"product_category: {product['product_category']}\n",
        encoding="utf-8",
    )


def product_brief_markdown(product: Dict[str, str]) -> str:
    return (
        "# 商品视频 Brief\n\n"
        f"- 视频类型：{product['video_type']}\n"
        f"- 商品名：{product['product_name'] or '待填写'}\n"
        f"- 类目：{product['product_category']}\n"
        f"- 目标平台：{product['target_platform']}\n"
        f"- 价格：{product['price'] or '待填写'}\n"
        f"- 佣金/利润：{product['commission'] or '待填写'}\n"
        f"- 痛点场景：{product['pain_point'] or '待填写'}\n"
        f"- 核心卖点：{product['selling_points'] or '待填写'}\n"
        f"- 商品链接：{product['product_link'] or '待填写'}\n"
        f"- 备注：{product['notes'] or '无'}\n"
    )


def _split_points(value: str) -> List[str]:
    return [part.strip() for part in value.replace("，", ",").replace("、", ",").split(",") if part.strip()]


def _scene_line(category: str) -> str:
    if "清洁" in category:
        return "先拍水槽、台面、油污、抹布这几个具体痛点，"
    if "调味" in category or "食材" in category:
        return "先拍下锅、翻炒、出锅和试吃反应，"
    if "小家电" in category:
        return "先拍开箱、占地、操作、清洗这几个关键细节，"
    return "先拍真实使用前后的变化，"
