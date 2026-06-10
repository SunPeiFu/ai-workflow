from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import http.client
from html import unescape
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PLATFORM_LABELS = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "xiaohongshu": "小红书",
    "unknown": "未知平台",
}
LLMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LLMSTUDIO_MODEL = "qwen3.6-27b-ud-mlx"
LLMSTUDIO_FAST_MODEL_PRIORITY = (
    "zai-org/glm-4.7-flash",
    "qwen3-coder-next-mlx",
    "gemma-4-31b-it-mlx",
    "qwen3.6-27b-ud-mlx",
)


def detect_short_video_platform(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    if "douyin" in host or "iesdouyin" in host:
        return "douyin"
    if "kuaishou" in host or "kwai" in host:
        return "kuaishou"
    if "xiaohongshu" in host or "xhslink" in host:
        return "xiaohongshu"
    return "unknown"


def analyze_remix_link(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_url = str(payload.get("url") or "").strip()
    share = parse_share_text(raw_url)
    url = share["url"]
    if not url:
        raise ValueError("请输入短视频链接")
    platform = detect_short_video_platform(url)
    tags = parse_tags(payload.get("tags"))
    images = parse_image_urls(payload.get("image_urls") or payload.get("images") or [])
    remote = {}
    if payload.get("fetch_remote", True) and platform == "xiaohongshu" and _needs_remote_metadata(payload, share, tags, images):
        remote = fetch_remix_metadata(url)
    title = str(payload.get("title") or "").strip() or remote.get("title", "") or share["title"]
    body = str(payload.get("body") or "").strip() or remote.get("body", "") or share["body"]
    tags = tags or remote.get("tags", [])
    images = images or remote.get("images", [])

    return {
        "ok": True,
        "url": url,
        "platform": platform,
        "platform_name": PLATFORM_LABELS.get(platform, PLATFORM_LABELS["unknown"]),
        "copywriting": {
            "title": title,
            "body": body,
            "tags": tags,
            "copy_text": copywriting_text(title, body, tags),
        },
        "images": [
            {
                "id": f"img-{index}",
                "url": image,
                "selected": True,
                "license_note": "来源链接拆解素材，二次发布前请确认授权或替换为自有素材。",
            }
            for index, image in enumerate(images, start=1)
        ],
        "optimization_items": remix_optimization_items(platform, title, body, tags, images),
    }


def parse_share_text(text: str) -> Dict[str, str]:
    raw = str(text or "").strip()
    match = re.search(r"https?://[^\s，。]+", raw)
    url = match.group(0).rstrip("。,.，") if match else raw
    prefix = raw[: match.start()].strip() if match else ""
    suffix = raw[match.end() :].strip() if match else ""
    share_text = clean_share_copy(prefix)
    if not share_text and suffix and "复制文字" not in suffix:
        share_text = clean_share_copy(suffix)
    title, body = split_share_title_body(share_text)
    return {"url": url, "title": title, "body": body}


def clean_share_copy(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"^\s*[\d.]+\s*", "", cleaned)
    cleaned = re.sub(r"复制打开抖音，?看看【[^】]+】", "", cleaned)
    cleaned = re.sub(r"复制打开抖音，?", "", cleaned)
    cleaned = re.sub(r"复制文字.*?(笔记|视频).*?呈现~?", "", cleaned, flags=re.S)
    cleaned = re.sub(r"打开【[^】]+】.*", "", cleaned, flags=re.S)
    cleaned = re.sub(r"\s+\d{1,2}/\d{1,2}\s+:[\w\s.@-]+Jip:/?.*$", "", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" \n\t，。")


def split_share_title_body(text: str) -> tuple[str, str]:
    compact = str(text or "").strip()
    if not compact:
        return "", ""
    product_match = re.search(r"(速干短裤|运动短裤|训练短裤|篮球短裤|短裤)", compact)
    if product_match:
        cut = product_match.end()
        return compact[:cut].strip(" ，。"), compact[cut:].strip()
    sentence_match = re.search(r"[。！？!?]", compact)
    if sentence_match:
        cut = sentence_match.end()
        title = compact[:cut].strip()
        body = compact[cut:].strip()
        return title, body
    if len(compact) <= 28:
        return compact, ""
    return compact[:28].strip(), compact[28:].strip()


def create_affiliate_remix_plan(analysis: Dict[str, Any], payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = payload or {}
    copywriting = analysis.get("copywriting") or {}
    title = str(copywriting.get("title") or "").strip()
    body = str(copywriting.get("body") or "").strip()
    tags = copywriting.get("tags") or []
    source_text = "\n".join(part for part in [title, body, format_tags(tags)] if part)
    product_name = str(payload.get("product_name") or infer_product_name(source_text)).strip() or "目标商品"
    category = str(payload.get("product_category") or infer_product_category(source_text)).strip() or "商品"
    selling_points = split_selling_points(payload.get("selling_points")) or infer_selling_points(source_text, category)
    pain_point = str(payload.get("pain_point") or infer_pain_point(category)).strip()

    douyin_titles = [
        f"{product_name}别只看颜色，打球训练更要看这几点",
        f"夏天运动短裤怎么选？这条路子更适合日常训练",
        f"打球出汗多，短裤选错真的很难受",
    ]
    xhs_titles = [
        f"{product_name}怎么选才不踩雷",
        f"夏天训练短裤，我会重点看这几个细节",
        f"日常打球也能穿的短裤，实用感比花色更重要",
    ]
    storyboard = [
        {"seconds": "0-3", "shot": "先拍运动/打球出汗场景", "purpose": "用真实痛点开场，不复刻原视频开头。"},
        {"seconds": "3-7", "shot": f"展示{product_name}版型、腰头和面料近景", "purpose": "换成自己的商品细节镜头。"},
        {"seconds": "7-13", "shot": "走动、深蹲、投篮或训练动作", "purpose": "证明运动场景适配。"},
        {"seconds": "13-18", "shot": "颜色/搭配快速切换", "purpose": "保留百搭卖点，但改变镜头顺序。"},
        {"seconds": "18-24", "shot": "总结适合人群和购买提醒", "purpose": "转化到橱窗，不照搬原话术。"},
    ]

    douyin_body = (
        f"如果你平时{pain_point}，选{product_name}别只看好不好看。"
        f"我会重点看{join_cn(selling_points[:3])}，适合训练、打球和日常通勤穿。"
        "拍摄时用自己的上身和运动镜头，别直接复用对标视频画面。"
    )
    xhs_body = (
        f"这类{category}我更建议从真实场景看：{pain_point}的时候，"
        f"{join_cn(selling_points[:3])}会比单纯颜色更重要。"
        "适合想要一条训练、打球、日常都能搭的短裤。"
    )
    platform_packages = {
        "douyin": {
            "titles": douyin_titles,
            "body": douyin_body,
            "tags": ["#运动短裤", "#速干短裤", "#打球穿搭", "#男生穿搭", "#好物分享"],
            "voiceover": affiliate_voiceover(product_name, selling_points, "douyin"),
            "cta": "想看上身和尺码建议，可以点橱窗看同款。",
        },
        "xiaohongshu": {
            "titles": xhs_titles,
            "body": xhs_body,
            "tags": ["#运动短裤", "#男生穿搭", "#夏季穿搭", "#篮球穿搭", "#训练好物"],
            "voiceover": affiliate_voiceover(product_name, selling_points, "xiaohongshu"),
            "cta": "评论区留身高体重，我按场景给你选尺码思路。",
        },
    }
    return {
        "ok": True,
        "source_url": analysis.get("url", ""),
        "source_platform": analysis.get("platform", ""),
        "product": {
            "name": product_name,
            "category": category,
            "selling_points": selling_points,
            "pain_point": pain_point,
        },
        "platform_packages": platform_packages,
        "storyboard": storyboard,
        "jianying_checklist": [
            "剪映中新建竖屏 9:16 项目，导入自有商品素材和上身/运动镜头。",
            "使用剪映 SVIP 模板、智能字幕、音色和转场，但不要套用原视频画面顺序。",
            "按分镜清单重排镜头：痛点、细节、运动测试、搭配、转化。",
            "导入本模块生成的口播稿，生成字幕后检查错字和商品风险词。",
        ],
        "dedupe_checks": [
            "不复用原视频画面、原声音和原字幕样式。",
            "不照搬原视频镜头顺序，至少重排开头、商品细节和结尾转化。",
            "标题、正文、标签全部原创改写，保留商品领域但换表达结构。",
            "使用自己的商品图、试穿图、训练动作或授权素材。",
            "BGM、字幕样式、封面文案和口播音色全部替换。",
        ],
        "risk_checks": affiliate_risk_checks(source_text),
    }


def create_affiliate_jianying_handoff(
    root: Path,
    analysis: Dict[str, Any],
    payload: Dict[str, Any] | None = None,
    package_name: str | None = None,
    launch: bool = False,
) -> Dict[str, Any]:
    plan = create_affiliate_remix_plan(analysis, payload)
    product_name = plan.get("product", {}).get("name") or "affiliate"
    handoff_dir = remix_package_dir(root, package_name or f"{product_name}-jianying", group="affiliate-jianying")
    handoff_dir.mkdir(parents=True, exist_ok=True)

    (handoff_dir / "analysis.json").write_text(json.dumps({"analysis": analysis, "plan": plan}, ensure_ascii=False, indent=2), encoding="utf-8")
    (handoff_dir / "口播稿.txt").write_text(affiliate_voiceover_text(plan), encoding="utf-8")
    (handoff_dir / "分镜清单.md").write_text(affiliate_storyboard_markdown(plan), encoding="utf-8")
    (handoff_dir / "抖音橱窗版.md").write_text(affiliate_platform_markdown("抖音橱窗版", plan["platform_packages"]["douyin"]), encoding="utf-8")
    (handoff_dir / "小红书种草版.md").write_text(affiliate_platform_markdown("小红书种草版", plan["platform_packages"]["xiaohongshu"]), encoding="utf-8")
    (handoff_dir / "剪映SVIP执行清单.md").write_text(affiliate_jianying_markdown(plan), encoding="utf-8")
    (handoff_dir / "判重检查.md").write_text(affiliate_checks_markdown(plan), encoding="utf-8")
    (handoff_dir / "素材占位说明.md").write_text(affiliate_asset_readme(plan), encoding="utf-8")

    app_path = find_jianying_app()
    launched = False
    if launch and app_path:
        result = subprocess.run(["open", str(app_path)], text=True, capture_output=True, check=False)
        launched = result.returncode == 0
    return {
        "ok": True,
        "handoff_dir": str(handoff_dir),
        "jianying_app": str(app_path) if app_path else "",
        "launched": launched,
        "files": [str(path) for path in sorted(handoff_dir.iterdir()) if path.is_file()],
        "plan": plan,
    }


def affiliate_voiceover_text(plan: Dict[str, Any]) -> str:
    packages = plan.get("platform_packages") or {}
    return (
        "抖音橱窗版口播\n"
        f"{packages.get('douyin', {}).get('voiceover', '')}\n\n"
        "小红书种草版口播\n"
        f"{packages.get('xiaohongshu', {}).get('voiceover', '')}\n"
    )


def affiliate_storyboard_markdown(plan: Dict[str, Any]) -> str:
    rows = ["# 分镜清单\n"]
    for item in plan.get("storyboard") or []:
        rows.append(f"- {item.get('seconds', '')} | {item.get('shot', '')} | {item.get('purpose', '')}")
    return "\n".join(rows) + "\n"


def affiliate_platform_markdown(title: str, package: Dict[str, Any]) -> str:
    rows = [f"# {title}\n", "## 标题候选"]
    rows.extend(f"- {value}" for value in package.get("titles") or [])
    rows.extend(
        [
            "\n## 正文",
            package.get("body", ""),
            "\n## 标签",
            " ".join(package.get("tags") or []),
            "\n## 口播",
            package.get("voiceover", ""),
            "\n## 转化话术",
            package.get("cta", ""),
        ]
    )
    return "\n".join(rows) + "\n"


def affiliate_jianying_markdown(plan: Dict[str, Any]) -> str:
    rows = ["# 剪映 SVIP 执行清单\n"]
    rows.extend(f"- {item}" for item in plan.get("jianying_checklist") or [])
    rows.extend(
        [
            "\n## 建议剪辑顺序",
            "1. 先导入自有商品素材、上身素材、训练/使用场景素材。",
            "2. 复制 `口播稿.txt` 到剪映文本朗读或人工配音。",
            "3. 使用智能字幕生成字幕，再手动检查商品名、价格、尺码。",
            "4. 用剪映 SVIP 模板/转场/BGM 增强节奏，但不要使用对标视频原素材。",
            "5. 导出抖音 9:16 视频后，再按小红书节奏微调封面和正文。",
        ]
    )
    return "\n".join(rows) + "\n"


def affiliate_checks_markdown(plan: Dict[str, Any]) -> str:
    rows = ["# 判重与风险检查\n", "## 降低判重"]
    rows.extend(f"- [ ] {item}" for item in plan.get("dedupe_checks") or [])
    rows.append("\n## 发布风险")
    rows.extend(f"- [ ] {item}" for item in plan.get("risk_checks") or [])
    return "\n".join(rows) + "\n"


def affiliate_asset_readme(plan: Dict[str, Any]) -> str:
    product = plan.get("product") or {}
    return (
        "# 素材占位说明\n\n"
        f"- 商品：{product.get('name', '待填写')}\n"
        f"- 类目：{product.get('category', '待填写')}\n"
        "- 请放入自有或授权商品图、上身图、运动/使用场景图。\n"
        "- 不建议直接下载并复用对标视频画面、声音、字幕和封面。\n"
        "- 剪映中优先使用自己的镜头顺序和字幕样式。\n"
    )


def split_selling_points(value: Any) -> List[str]:
    raw = str(value or "").replace("，", ",").replace("、", ",")
    return [part.strip() for part in raw.split(",") if part.strip()]


def infer_product_name(text: str) -> str:
    if "短裤" in text:
        return "速干运动短裤" if "速干" in text else "运动短裤"
    return "橱窗商品"


def infer_product_category(text: str) -> str:
    if "短裤" in text or "训练" in text or "打球" in text:
        return "运动服饰"
    return "精选好物"


def infer_selling_points(text: str, category: str) -> List[str]:
    points = []
    for keyword in ["速干", "百搭", "训练", "打球", "日常", "颜色"]:
        if keyword in text and keyword not in points:
            points.append(keyword)
    return points or (["场景明确", "使用顺手", "转化理由清楚"] if category != "运动服饰" else ["速干", "百搭", "适合训练"])


def infer_pain_point(category: str) -> str:
    if category == "运动服饰":
        return "打球训练容易出汗、普通短裤闷又不方便活动"
    return "日常使用里想买得更省心"


def join_cn(items: List[str]) -> str:
    if not items:
        return "使用场景、细节和性价比"
    if len(items) == 1:
        return items[0]
    return "、".join(items[:-1]) + "和" + items[-1]


def affiliate_voiceover(product_name: str, selling_points: List[str], platform: str) -> str:
    platform_tail = "点橱窗看同款，先按自己的运动场景选。" if platform == "douyin" else "更适合收藏起来，对照自己的穿搭和运动场景慢慢选。"
    return (
        f"夏天打球或者训练，短裤真的别随便买。"
        f"这类{product_name}我会先看{join_cn(selling_points[:3])}。"
        "镜头里一定要拍实际走动、下蹲和运动状态，光看颜色不够。"
        f"{platform_tail}"
    )


def affiliate_risk_checks(text: str) -> List[str]:
    risks = ["不要承诺销量、最低价、全网第一等绝对化表达。"]
    if "速干" in text:
        risks.append("速干属于商品卖点，建议拍面料和运动后状态，不要夸大成医疗/身体效果。")
    if not text.strip():
        risks.append("原始素材信息不足，发布前需要人工补充商品链接、价格、尺码和授权素材。")
    return risks


def _needs_remote_metadata(payload: Dict[str, Any], share: Dict[str, str], tags: List[str], images: List[str]) -> bool:
    return not (
        str(payload.get("title") or "").strip()
        and str(payload.get("body") or "").strip()
        and tags
        and images
    ) or not (share.get("title") and share.get("body") and tags and images)


def fetch_remix_metadata(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            html = response.read(1_500_000).decode("utf-8", errors="ignore")
    except Exception:
        return {}
    metadata = parse_remix_html_metadata(html)
    if metadata:
        metadata["resolved_url"] = response.geturl()
    return metadata


def parse_remix_html_metadata(html: str) -> Dict[str, Any]:
    fields = extract_meta_fields(html)
    title = clean_remote_title(
        first_meta(fields, "og:title")
        or first_meta(fields, "twitter:title")
        or extract_title_tag(html)
    )
    body = (
        first_meta(fields, "description")
        or first_meta(fields, "og:description")
        or first_meta(fields, "twitter:description")
        or ""
    ).strip()
    tags = parse_tags(first_meta(fields, "keywords"))
    body_tags = parse_tags(" ".join(re.findall(r"#[\w\u4e00-\u9fff-]+", body)))
    body = strip_inline_tags(body)
    for tag in body_tags:
        if tag not in tags:
            tags.append(tag)
    images = []
    for key in ("og:image", "twitter:image"):
        for image in fields.get(key, []):
            if image and image not in images:
                images.append(image)
    return {"title": title, "body": body, "tags": tags, "images": images}


def extract_meta_fields(html: str) -> Dict[str, List[str]]:
    fields: Dict[str, List[str]] = {}
    for attrs_text in re.findall(r"<meta\s+([^>]+)>", html, flags=re.I):
        attrs = dict(
            (name.lower(), unescape(value))
            for name, value in re.findall(r"([\w:-]+)=[\"']([^\"']*)[\"']", attrs_text)
        )
        key = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content", "").strip()
        if key and content:
            fields.setdefault(key, []).append(content)
    return fields


def strip_inline_tags(text: str) -> str:
    cleaned = re.sub(r"#[\w\u4e00-\u9fff-]+", "", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def first_meta(fields: Dict[str, List[str]], key: str) -> str:
    values = fields.get(key.lower()) or []
    return values[0].strip() if values else ""


def clean_remote_title(title: str) -> str:
    cleaned = unescape(str(title or "")).strip()
    cleaned = re.sub(r"\s*-\s*小红书\s*$", "", cleaned)
    return cleaned.strip()


def extract_title_tag(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return unescape(re.sub(r"\s+", " ", match.group(1)).strip()) if match else ""


def create_remix_package(root: Path, analysis: Dict[str, Any], package_name: str | None = None) -> Dict[str, Any]:
    package_dir = remix_package_dir(root, package_name)
    remove_existing_remix_packages_for_source(root, analysis, keep_dir=package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    copywriting = analysis.get("copywriting") or {}
    original_title = copywriting.get("title") or "待补充标题"
    original_body = copywriting.get("body") or "待补充正文"
    tags = copywriting.get("tags") or []
    rewritten_title = rewrite_title(original_title)
    rewritten_body = rewrite_body(original_body)

    (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_dir / "copywriting.md").write_text(
        "# 图文包\n\n"
        f"## 原标题\n{original_title}\n\n"
        f"## 原正文\n{original_body}\n\n"
        f"## 原标签\n{format_tags(tags)}\n\n"
        f"## 原创改写标题\n{rewritten_title}\n\n"
        f"## 原创改写正文\n{rewritten_body}\n\n"
        f"## 推荐标签\n{format_tags(remix_tags(tags))}\n",
        encoding="utf-8",
    )
    (package_dir / "image-package.md").write_text(image_package_markdown(analysis), encoding="utf-8")
    (package_dir / "video-script.txt").write_text(
        video_script_from_analysis(analysis, rewritten_title, rewritten_body),
        encoding="utf-8",
    )
    (package_dir / "publish-checklist.md").write_text(remix_publish_checklist(), encoding="utf-8")
    packages_root = (Path(root) / "remix_packages").resolve()
    return {
        "ok": True,
        "package_dir": str(package_dir),
        "package_path": package_dir.resolve().relative_to(packages_root).as_posix(),
        "copywriting": str(package_dir / "copywriting.md"),
    }


def remove_existing_remix_packages_for_source(root: Path, analysis: Dict[str, Any], keep_dir: Path | None = None) -> None:
    source_url = str(analysis.get("url") or "").strip()
    if not source_url:
        return
    remix_root = Path(root) / "remix_packages" / "remix"
    if not remix_root.exists():
        return
    keep_resolved = keep_dir.resolve() if keep_dir else None
    for package_dir in remix_root.iterdir():
        if not package_dir.is_dir():
            continue
        if keep_resolved and package_dir.resolve() == keep_resolved:
            continue
        analysis_path = package_dir / "analysis.json"
        if not analysis_path.exists():
            continue
        try:
            package_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(package_analysis.get("url") or "").strip() == source_url:
            shutil.rmtree(package_dir)


def create_jianying_handoff(
    root: Path,
    analysis: Dict[str, Any],
    package_name: str | None = None,
    launch: bool = False,
) -> Dict[str, Any]:
    handoff_dir = remix_package_dir(root, package_name, group="jianying")
    handoff_dir.mkdir(parents=True, exist_ok=True)
    copywriting = analysis.get("copywriting") or {}
    title = rewrite_title(copywriting.get("title") or "待补充标题")
    body = rewrite_body(copywriting.get("body") or "待补充正文")
    text = f"{title}\n\n{body}\n\n{format_tags(remix_tags(copywriting.get('tags') or []))}\n"

    (handoff_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    (handoff_dir / "文案.txt").write_text(text, encoding="utf-8")
    (handoff_dir / "镜头清单.md").write_text(image_package_markdown(analysis), encoding="utf-8")
    (handoff_dir / "剪映导入说明.md").write_text(jianying_readme(analysis), encoding="utf-8")

    app_path = find_jianying_app()
    launched = False
    if launch and app_path:
        result = subprocess.run(["open", str(app_path)], text=True, capture_output=True, check=False)
        launched = result.returncode == 0
    return {
        "ok": True,
        "handoff_dir": str(handoff_dir),
        "jianying_app": str(app_path) if app_path else "",
        "launched": launched,
    }


def optimize_copy_with_llmstudio(payload: Dict[str, Any]) -> Dict[str, Any]:
    field = str(payload.get("field") or "body").strip()
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("请先提供需要优化润色的文本")
    base_url = str(payload.get("base_url") or LLMSTUDIO_BASE_URL).rstrip("/")
    model = str(payload.get("model") or "").strip() or available_llmstudio_model(base_url) or LLMSTUDIO_MODEL
    allow_emoji = bool(payload.get("allow_emoji"))
    request_payload = llmstudio_payload(field, text, model, allow_emoji=allow_emoji)
    try:
        data = local_json_request(f"{base_url}/chat/completions", method="POST", payload=request_payload, timeout=180)
    except Exception as exc:
        raise RuntimeError(f"调用本地 LM Studio 失败: {exc}") from exc
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    suggestions = normalize_copy_suggestions(
        field,
        parse_llmstudio_suggestions(content),
        allow_emoji=allow_emoji,
        source_text=text,
    )
    if len(suggestions) < 3:
        raise RuntimeError("本地模型没有返回 3 个可用候选，请重试")
    return {"ok": True, "field": field, "model": model, "allow_emoji": allow_emoji, "suggestions": suggestions[:3], "raw": content}


def available_llmstudio_model(base_url: str = LLMSTUDIO_BASE_URL) -> str:
    return list_llmstudio_models(base_url).get("default_model", "")


def list_llmstudio_models(base_url: str = LLMSTUDIO_BASE_URL) -> Dict[str, Any]:
    try:
        data = local_json_request(f"{base_url.rstrip('/')}/models", timeout=5)
    except Exception as exc:
        return {"ok": False, "error": f"无法读取 LM Studio 模型列表: {exc}", "models": [], "default_model": LLMSTUDIO_MODEL}
    return summarize_llmstudio_models(data)


def summarize_llmstudio_models(data: Dict[str, Any]) -> Dict[str, Any]:
    model_ids = []
    for item in data.get("data") or []:
        model_id = str(item.get("id") or "").strip()
        if model_id and "embedding" not in model_id.lower() and model_id not in model_ids:
            model_ids.append(model_id)
    default_model = preferred_llmstudio_model(model_ids) or LLMSTUDIO_MODEL
    ordered = [default_model, *[model_id for model_id in model_ids if model_id != default_model]]
    return {
        "ok": True,
        "models": [
            {
                "id": model_id,
                "label": llmstudio_model_label(model_id),
                "recommended": model_id == default_model,
            }
            for model_id in ordered
        ],
        "default_model": default_model,
    }


def preferred_llmstudio_model(model_ids: List[str]) -> str:
    available = [model_id for model_id in model_ids if model_id and "embedding" not in model_id.lower()]
    by_lower = {model_id.lower(): model_id for model_id in available}
    for preferred in LLMSTUDIO_FAST_MODEL_PRIORITY:
        match = by_lower.get(preferred.lower())
        if match:
            return match
    return available[0] if available else ""


def llmstudio_model_label(model_id: str) -> str:
    labels = {
        "zai-org/glm-4.7-flash": "GLM 4.7 Flash（推荐，润色更快）",
        "qwen3-coder-next-mlx": "Qwen3 Coder Next（较快，适合结构化改写）",
        "gemma-4-31b-it-mlx": "Gemma 4 31B（质量优先）",
        "qwen3.6-27b-ud-mlx": "Qwen3.6 27B（质量高，速度慢）",
    }
    return labels.get(model_id, model_id)


def local_json_request(url: str, method: str = "GET", payload: Dict[str, Any] | None = None, timeout: int = 30) -> Dict[str, Any]:
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port or 80, timeout=timeout)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer lm-studio"}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    text = response.read().decode("utf-8", errors="ignore")
    connection.close()
    if response.status >= 400:
        raise RuntimeError(f"HTTP {response.status}: {text[:300]}")
    return json.loads(text)


def llmstudio_payload(field: str, text: str, model: str = LLMSTUDIO_MODEL, allow_emoji: bool = False) -> Dict[str, Any]:
    field_name = {"title": "标题", "body": "正文", "tags": "标签"}.get(field, "文案")
    field_rules = llmstudio_field_rules(field, allow_emoji, source_text=text)
    return {
        "model": model,
        "temperature": 0.75,
        "max_tokens": {"title": 2200, "tags": 2200}.get(field, 3600),
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是短视频/图文平台的中文文案优化助手。"
                    "只返回 JSON 数组，不要解释，不要 Markdown，不要输出思考过程。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请基于下面的{field_name}生成 3 个优化润色版本。"
                    "核心原则：必须围绕输入内容，整体语义主旨一致；"
                    "通过表达结构、措辞、节奏和细节顺序重写，防止二次加工平台判重，降低三方平台判重风险；"
                    "表达要像真人发布，不要太 AI 味；不要编造事实。"
                    f"{field_rules}\n\n"
                    f"原文：\n{text}\n\n/no_think"
                ),
            },
        ],
    }


def llmstudio_field_rules(field: str, allow_emoji: bool, source_text: str = "") -> str:
    source_emojis = extract_emojis(source_text, limit=8)
    if source_emojis:
        emoji_rule = (
            f"原文带有 emoji（{' '.join(source_emojis)}），每个候选输出必须包含 emoji 表情，必须保留 emoji 风格；"
            "可以使用原 emoji，也可以替换为颜色、形状或语义相近的 emoji；"
            "位置要自然，不要堆砌。"
        )
    elif allow_emoji:
        emoji_rule = "可以加入少量小红书主流 emoji，位置自然，不要堆砌。"
    else:
        emoji_rule = "不要加入 emoji 表情。"
    if field == "title":
        return (
            f"标题要求：{emoji_rule}"
            "标题里不要带 # 符号；不要写成标签；保留原文核心事件、对象和判断；"
            "标题要有平台感，但不要夸张到改变事实。"
        )
    if field == "tags":
        return (
            "标签要求：每个标签都必须以 # 开头；围绕输入标签所在领域适当扩展，不能跨领域发散；"
            "例如原始输入 #戒色 #男性成长，可以输出 #男性戒色 #自我提升 #心灵成长；"
            "每个候选返回一组标签，标签之间用空格分隔。"
        )
    return (
        f"正文要求：{emoji_rule}"
        "正文里不要带 # 符号；主旨不变，保留原文核心事实和因果关系；"
        "可以调整表达顺序和口语化程度，让它更像真实小红书/短视频正文。"
    )


def parse_llmstudio_suggestions(content: str) -> List[str]:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = parse_first_json_array(text)
    if isinstance(parsed, dict):
        parsed = parsed.get("suggestions") or parsed.get("items") or parsed.get("data")
    if not isinstance(parsed, list):
        return parse_suggestion_lines(text)
    suggestions = []
    for item in parsed:
        value = str(item).strip()
        if value and value not in suggestions:
            suggestions.append(value)
    return suggestions


def parse_first_json_array(text: str) -> Any:
    start = str(text or "").find("[")
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def parse_suggestion_lines(text: str) -> List[str]:
    suggestions = []
    for line in str(text or "").splitlines():
        value = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).strip()
        value = value.strip("\"'“”")
        if value and value not in suggestions:
            suggestions.append(value)
    return suggestions


def normalize_copy_suggestions(
    field: str,
    suggestions: List[str],
    allow_emoji: bool = False,
    source_text: str = "",
) -> List[str]:
    source_emojis = extract_emojis(source_text, limit=3)
    normalized = []
    for suggestion in suggestions:
        if field == "tags":
            value = normalize_tag_suggestion(suggestion)
        else:
            value = re.sub(r"#\s*", "", str(suggestion or ""))
            value = re.sub(r"\s+", " ", value).strip()
            if field in {"title", "body"} and (allow_emoji or source_emojis):
                value = ensure_copy_emoji(field, value, source_emojis=source_emojis)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def ensure_copy_emoji(field: str, value: str, source_emojis: List[str] | None = None) -> str:
    text = str(value or "").strip()
    if not text or has_common_emoji(text):
        return text
    prefix = (source_emojis or [])[0] if source_emojis else ("✨" if field == "title" else "📝")
    return f"{prefix} {text}"


def has_common_emoji(text: str) -> bool:
    return bool(extract_emojis(text, limit=1))


def extract_emojis(text: str, limit: int = 6) -> List[str]:
    emojis = []
    for match in re.finditer(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", str(text or "")):
        emoji = match.group(0)
        if emoji not in emojis:
            emojis.append(emoji)
        if len(emojis) >= limit:
            break
    return emojis


def normalize_tag_suggestion(value: str) -> str:
    tags = []
    raw = str(value or "").replace("，", " ").replace(",", " ").replace("、", " ")
    for part in raw.split():
        cleaned = part.strip().removeprefix("#")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return " ".join(f"#{tag}" for tag in tags)


def parse_tags(value: Any) -> List[str]:
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    else:
        raw = str(value or "")
    normalized = raw.replace("，", ",").replace("、", ",").replace("#", " #")
    tags = []
    for part in normalized.replace("\n", " ").split():
        for chunk in part.split(","):
            cleaned = chunk.strip().removeprefix("#")
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
    return tags


def parse_image_urls(value: Any) -> List[str]:
    if isinstance(value, str):
        candidates = value.replace(",", "\n").splitlines()
    else:
        candidates = [str(item) for item in value]
    images = []
    for candidate in candidates:
        url = candidate.strip()
        if url and url not in images:
            images.append(url)
    return images


def copywriting_text(title: str, body: str, tags: List[str]) -> str:
    return "\n\n".join(part for part in [title, body, format_tags(tags)] if part)


def format_tags(tags: List[str]) -> str:
    return " ".join(f"#{tag}" for tag in tags)


def remix_optimization_items(platform: str, title: str, body: str, tags: List[str], images: List[str]) -> List[str]:
    items = ["改成原创角度：保留痛点，不复刻原视频表述和镜头顺序。"]
    if not title:
        items.append("补充标题：最好包含具体人群、场景或结果。")
    if len(body) < 40:
        items.append("正文偏短：补充使用前后、对比理由和适合/不适合人群。")
    if not tags:
        items.append("补充标签：至少保留 3 个平台搜索词。")
    if not images:
        items.append("图片不足：请导入自有图片或授权素材再生成图文包。")
    if platform == "douyin":
        items.append("抖音优化：前三秒先给冲突和结果，再讲步骤。")
    elif platform == "xiaohongshu":
        items.append("小红书优化：增加真实体验、使用场景和避坑语气。")
    elif platform == "kuaishou":
        items.append("快手优化：表达更生活化，保留明确购买理由。")
    return items


def remix_package_dir(root: Path, package_name: str | None = None, group: str = "remix") -> Path:
    safe_name = safe_package_name(package_name or f"{group}-{int(time.time())}")
    return Path(root) / "remix_packages" / group / safe_name


def safe_package_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    return cleaned or f"package-{int(time.time())}"


def rewrite_title(title: str) -> str:
    title = title.strip() or "这类内容别直接照着拍"
    return f"原创改写：{title}，我会换个角度重新讲"


def rewrite_body(body: str) -> str:
    body = body.strip() or "原内容信息不足，请补充正文后再生成。"
    return (
        "这条内容我不直接复刻原表达，而是保留问题场景，重新拆成自己的体验："
        f"{body} 接下来重点讲清楚使用前的问题、替代方案、实际变化和适合人群。"
    )


def remix_tags(tags: List[str]) -> List[str]:
    defaults = ["原创改写", "好物分享", "避坑"]
    result = []
    for tag in [*tags, *defaults]:
        if tag and tag not in result:
            result.append(tag)
    return result[:8]


def image_package_markdown(analysis: Dict[str, Any]) -> str:
    rows = []
    for image in analysis.get("images") or []:
        rows.append(f"- [ ] {image.get('url', '')} | {image.get('license_note', '待确认授权')}")
    if not rows:
        rows.append("- [ ] 待导入自有图片或授权素材")
    return "# 图片素材包\n\n" + "\n".join(rows) + "\n"


def video_script_from_analysis(analysis: Dict[str, Any], title: str, body: str) -> str:
    platform_name = analysis.get("platform_name") or "目标平台"
    return (
        f"原创改写视频脚本\n\n"
        f"标题：{title}\n\n"
        f"开头：先说明这条不是复刻原视频，而是基于同类问题做一次原创拆解。\n\n"
        f"正文：{body}\n\n"
        f"镜头建议：按问题场景、细节展示、前后对比、结论四段组织素材。\n\n"
        f"发布平台：{platform_name}\n"
    )


def remix_publish_checklist() -> str:
    return (
        "# 发布前检查\n\n"
        "- [ ] 已确认原链接素材授权，未搬运原视频画面/声音\n"
        "- [ ] 标题、正文、标签已做原创改写\n"
        "- [ ] 图片为自有素材、授权素材或重新生成素材\n"
        "- [ ] 已检查平台违禁词和夸大承诺\n"
    )


def jianying_readme(analysis: Dict[str, Any]) -> str:
    return (
        "# 剪映导入说明\n\n"
        "1. 打开剪映，新建项目。\n"
        "2. 将本目录的 `文案.txt` 作为口播/字幕参考。\n"
        "3. 按 `镜头清单.md` 导入自有图片或授权素材。\n"
        "4. 不建议直接搬运原链接的视频画面和声音；请做原创改写和素材替换。\n\n"
        f"来源链接：{analysis.get('url', '')}\n"
    )


def find_jianying_app() -> Path | None:
    candidates = [
        Path("/Applications/剪映专业版.app"),
        Path("/Applications/剪映.app"),
        Path("/Applications/CapCut.app"),
        Path.home() / "Applications" / "剪映专业版.app",
        Path.home() / "Applications" / "CapCut.app",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = shutil.which("CapCut")
    return Path(found) if found else None
