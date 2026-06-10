from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_PLATFORMS = ("bilibili", "xiaohongshu", "douyin")
TITLE_EXPERIMENT_COLUMNS = [
    "platform",
    "platform_name",
    "variant_index",
    "title",
    "hypothesis",
    "selected",
    "publish_url",
    "views",
    "click_rate",
    "notes",
]


@dataclass(frozen=True)
class PlatformPreset:
    key: str
    name: str
    aspect_ratio: str
    target_size: str
    title_limit: int
    tag_limit: int
    description_style: str
    traffic_goal: str


PLATFORM_PRESETS = {
    "bilibili": PlatformPreset(
        key="bilibili",
        name="哔哩哔哩",
        aspect_ratio="16:9",
        target_size="1920x1080",
        title_limit=80,
        tag_limit=10,
        description_style="观点完整、可信来源、系列归档",
        traffic_goal="提高点击率、完播率、收藏和评论讨论",
    ),
    "xiaohongshu": PlatformPreset(
        key="xiaohongshu",
        name="小红书",
        aspect_ratio="4:5",
        target_size="1080x1350",
        title_limit=20,
        tag_limit=8,
        description_style="真实体验、可收藏清单、低攻击性表达",
        traffic_goal="提高封面点击、收藏、评论和私域转化",
    ),
    "douyin": PlatformPreset(
        key="douyin",
        name="抖音",
        aspect_ratio="9:16",
        target_size="1080x1920",
        title_limit=28,
        tag_limit=6,
        description_style="前三秒强钩子、短句、系列切片",
        traffic_goal="提高首屏停留、完播率、转粉和直播/橱窗转化",
    ),
}

RISK_TERMS = {
    "health": ("治疗", "治愈", "疗效", "抑郁", "焦虑", "心理疾病", "药", "医学"),
    "sexual": ("性", "看片", "女人", "男人", "无能", "欲望", "色情"),
    "absolute": ("一定", "彻底", "必然", "永久", "所有人", "百分百", "绝对"),
    "attack": ("废物", "垃圾", "低级", "脑残", "无能"),
}


def normalize_platforms(platforms: Iterable[str] | None) -> List[str]:
    selected = [platform for platform in (platforms or DEFAULT_PLATFORMS) if platform in PLATFORM_PRESETS]
    return selected or list(DEFAULT_PLATFORMS)


def write_platform_packages(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> List[Path]:
    package_root = project_dir / "exports" / "platforms"
    package_root.mkdir(parents=True, exist_ok=True)
    written = []
    selected_platforms = normalize_platforms(platforms)
    for key in selected_platforms:
        preset = PLATFORM_PRESETS[key]
        package_dir = package_root / key
        package_dir.mkdir(parents=True, exist_ok=True)
        metadata = platform_metadata(preset, script_text, duration)
        (package_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (package_dir / "publish.md").write_text(render_platform_publish_markdown(metadata), encoding="utf-8")
        (package_dir / "cover.svg").write_text(render_cover_svg(metadata), encoding="utf-8")
        written.append(package_dir)
    write_title_experiments(project_dir, script_text, duration, selected_platforms)
    write_hook_analysis(project_dir, script_text, duration, selected_platforms)
    write_monetization_plan(project_dir, script_text, duration, selected_platforms)
    write_series_plan(project_dir, script_text, duration, selected_platforms)
    write_publish_schedule(project_dir, script_text, duration, selected_platforms)
    return written


def write_publish_schedule(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> Path:
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "publish-schedule.json"
    path.write_text(
        json.dumps(publish_schedule(script_text, duration, platforms), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def publish_schedule(script_text: str, duration: float, platforms: Iterable[str] | None = None) -> dict:
    selected = normalize_platforms(platforms)
    series = series_plan(script_text, duration, selected)
    slots = []
    for offset, episode in enumerate(series["episodes"][: min(9, len(series["episodes"]))]):
        preset = PLATFORM_PRESETS[episode["platform"]]
        slots.append(
            {
                "day": f"D+{offset}",
                "platform": preset.key,
                "platform_name": preset.name,
                "time_window": publish_time_window(preset, offset),
                "title": episode["title"],
                "asset": publish_asset_hint(preset),
                "pre_publish_checklist": pre_publish_checklist(preset),
                "observe_after_hours": observe_after_hours(preset),
                "decision_rule": publish_decision_rule(preset),
            }
        )
    return {
        "topic": series["topic"],
        "cadence": "先连续 7 天测试同主题，再按复盘数据加码表现最好的平台。",
        "slots": slots,
        "daily_review": ["发布后 2 小时记录初始数据", "发布后 24 小时回填 performance.csv", "把高表现标题写回标题实验结论"],
        "scale_rule": "若某平台连续 2 条表现最佳，下一轮系列优先为该平台做原生版本。",
    }


def publish_time_window(preset: PlatformPreset, offset: int) -> str:
    if preset.key == "bilibili":
        return "19:30-22:30"
    if preset.key == "xiaohongshu":
        return "12:00-13:30 或 20:00-22:30"
    return "11:30-13:00 或 18:00-22:00" if offset % 2 else "18:00-22:00"


def publish_asset_hint(preset: PlatformPreset) -> str:
    if preset.key == "bilibili":
        return "横版视频 + 完整简介 + 置顶评论"
    if preset.key == "xiaohongshu":
        return "4:5 视频 + 收藏型封面 + 正文清单"
    return "竖版短视频 + 强字幕 + 下一条预告"


def pre_publish_checklist(preset: PlatformPreset) -> List[str]:
    base = ["标题已选主推版本", "封面文字手机端可读", "字幕无错别字", "评论区 CTA 已准备"]
    if preset.key == "bilibili":
        return base + ["简介补充系列入口", "合集/分区已选择"]
    if preset.key == "xiaohongshu":
        return base + ["正文有可收藏清单", "标签不超过建议数量"]
    return base + ["前三秒直接抛冲突", "结尾关注理由明确"]


def observe_after_hours(preset: PlatformPreset) -> List[int]:
    if preset.key == "bilibili":
        return [2, 24, 72]
    return [1, 6, 24]


def publish_decision_rule(preset: PlatformPreset) -> str:
    if preset.key == "bilibili":
        return "24 小时收藏率和评论质量高于其他平台时，加做长版补充或合集。"
    if preset.key == "xiaohongshu":
        return "收藏率或私信数最高时，下一条改成更强清单/模板型内容。"
    return "3 秒留存或转粉率最高时，连续拆 3 条同冲突点短视频。"


def write_series_plan(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> Path:
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "series-plan.json"
    path.write_text(
        json.dumps(series_plan(script_text, duration, platforms), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def series_plan(script_text: str, duration: float, platforms: Iterable[str] | None = None) -> dict:
    topic = title_seed_from_script(script_text)
    selected = normalize_platforms(platforms)
    pillars = series_pillars(script_text)
    episodes = []
    index = 1
    for pillar in pillars:
        for key in selected:
            preset = PLATFORM_PRESETS[key]
            episodes.append(series_episode(index, preset, topic, pillar))
            index += 1
    return {
        "topic": topic,
        "series_name": f"{topic[:18]}系列",
        "cadence": "建议连续发布 5-9 条，同主题不同角度测试标题、封面和前三秒。",
        "platforms": selected,
        "pillars": pillars,
        "episodes": episodes[: max(6, len(selected) * 3)],
        "reuse_notes": series_reuse_notes(selected),
        "duration_seconds": round(duration, 3),
    }


def series_pillars(script_text: str) -> List[str]:
    pillars = ["误区纠偏", "原因机制", "自查清单", "行动步骤", "案例拆解"]
    if any(term in script_text for term in ("流量", "涨粉", "变现", "视频", "发布")):
        return ["流量误区", "标题封面", "前三秒钩子", "发布复盘", "变现承接"]
    if any(term in script_text for term in RISK_TERMS["sexual"]):
        return ["常见误解", "行为机制", "关系沟通", "自我调整", "边界提醒"]
    if any(term in script_text for term in RISK_TERMS["health"]):
        return ["风险澄清", "科学边界", "日常自查", "求助路径", "误区纠偏"]
    return pillars


def series_episode(index: int, preset: PlatformPreset, topic: str, pillar: str) -> dict:
    title = series_title(preset, topic, pillar)
    return {
        "index": index,
        "platform": preset.key,
        "platform_name": preset.name,
        "pillar": pillar,
        "title": title,
        "hook": series_hook(preset, topic, pillar),
        "format": series_format(preset),
        "cta": series_cta(preset, pillar),
        "success_metric": series_metric(preset),
    }


def series_title(preset: PlatformPreset, topic: str, pillar: str) -> str:
    if preset.key == "bilibili":
        title = f"{topic}：{pillar}这一点很多人忽略了"
    elif preset.key == "xiaohongshu":
        title = f"{pillar}：{topic[:10]}先看这个"
    else:
        title = f"{topic[:12]}，{pillar}说透"
    return title[: preset.title_limit]


def series_hook(preset: PlatformPreset, topic: str, pillar: str) -> str:
    if preset.key == "douyin":
        return f"如果你也卡在“{topic[:14]}”，先听这句关于{pillar}的反常识。"
    if preset.key == "xiaohongshu":
        return f"很多人以为{topic[:14]}只能硬扛，其实可以从{pillar}开始。"
    return f"这期不讲大道理，只把{topic[:16]}里的{pillar}拆清楚。"


def series_format(preset: PlatformPreset) -> str:
    if preset.key == "bilibili":
        return "6-12 分钟结构化口播，保留完整论证和评论讨论问题。"
    if preset.key == "xiaohongshu":
        return "60-120 秒收藏型短视频，画面用结论卡和清单卡。"
    return "30-60 秒强钩子短视频，前 3 秒直接抛冲突。"


def series_cta(preset: PlatformPreset, pillar: str) -> str:
    if preset.key == "bilibili":
        return f"评论区打“{pillar}”，下一期继续展开。"
    if preset.key == "xiaohongshu":
        return f"需要{pillar}清单可以评论“清单”。"
    return f"关注我，下一条继续讲{pillar}。"


def series_metric(preset: PlatformPreset) -> str:
    if preset.key == "bilibili":
        return "点击率、完播率、收藏率、长评论数量"
    if preset.key == "xiaohongshu":
        return "收藏率、评论关键词、私信数"
    return "3 秒留存、完播率、转粉率、关键词评论"


def series_reuse_notes(platforms: Sequence[str]) -> List[str]:
    notes = ["同一主题先做 1 条完整版，再拆 2-4 条短版测试不同钩子。"]
    if "bilibili" in platforms:
        notes.append("B 站版本沉淀完整观点，后续短平台引用该视频作为系列源头。")
    if "xiaohongshu" in platforms:
        notes.append("小红书版本优先做清单化封面，强化收藏和私信承接。")
    if "douyin" in platforms:
        notes.append("抖音版本每条只讲一个冲突点，结尾用下一条预告做连播。")
    return notes


def write_monetization_plan(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> Path:
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "monetization-plan.json"
    path.write_text(
        json.dumps(monetization_plan(script_text, duration, platforms), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def monetization_plan(script_text: str, duration: float, platforms: Iterable[str] | None = None) -> dict:
    topic = title_seed_from_script(script_text)
    selected = normalize_platforms(platforms)
    offers = monetization_offers(script_text, topic)
    return {
        "topic": topic,
        "primary_offer": offers[0],
        "offer_ladder": offers,
        "platform_routes": {key: platform_monetization_route(PLATFORM_PRESETS[key], topic, offers) for key in selected},
        "profile_checklist": profile_checklist(topic),
        "comment_templates": comment_templates(topic),
        "risk_notes": monetization_risk_notes(script_text),
        "duration_seconds": round(duration, 3),
    }


def monetization_offers(script_text: str, topic: str) -> List[dict]:
    if any(term in script_text for term in ("剪辑", "视频", "流量", "涨粉", "变现", "发布")):
        return [
            {"level": "free", "name": f"{topic[:18]}检查清单", "goal": "用资料包换关注、收藏和私信线索。"},
            {"level": "entry", "name": "账号诊断/选题诊断", "goal": "低门槛转化高意向用户。"},
            {"level": "core", "name": "短视频工作流陪跑", "goal": "转化为咨询、课程或服务。"},
        ]
    if any(term in script_text for term in RISK_TERMS["sexual"] + RISK_TERMS["health"]):
        return [
            {"level": "free", "name": f"{topic[:18]}自查表", "goal": "先提供低风险科普型资料，避免医疗化承诺。"},
            {"level": "entry", "name": "关系/习惯复盘模板", "goal": "承接收藏用户，沉淀长期信任。"},
            {"level": "core", "name": "付费资料包或社群", "goal": "只做经验整理，不替代专业建议。"},
        ]
    return [
        {"level": "free", "name": f"{topic[:18]}行动清单", "goal": "提高收藏和私信触发。"},
        {"level": "entry", "name": "主题资料包", "goal": "把泛流量筛成高意向用户。"},
        {"level": "core", "name": "咨询/社群/课程", "goal": "围绕系列内容做长期转化。"},
    ]


def platform_monetization_route(preset: PlatformPreset, topic: str, offers: Sequence[dict]) -> dict:
    free_offer = offers[0]["name"]
    if preset.key == "bilibili":
        return {
            "entry_point": "置顶评论 + 简介关键词",
            "cta": f"需要《{free_offer}》可以在评论区打“清单”，我会整理到下一期置顶。",
            "conversion_path": ["视频收藏", "评论关键词", "主页合集", "私信/动态领取资料", "转化到资料包或服务"],
            "best_metric": "收藏率 + 评论关键词数量",
        }
    if preset.key == "xiaohongshu":
        return {
            "entry_point": "正文末尾 + 置顶评论 + 主页简介",
            "cta": f"想要《{free_offer}》可以评论“清单”，我整理成可保存版本。",
            "conversion_path": ["收藏笔记", "评论关键词", "私信领取", "主页承接", "资料包/咨询转化"],
            "best_metric": "收藏率 + 私信数",
        }
    return {
        "entry_point": "视频结尾口播 + 评论区关键词",
        "cta": f"想要《{free_offer}》，评论区打“清单”，下一条继续拆。",
        "conversion_path": ["完播", "关注", "评论关键词", "主页置顶视频", "直播/橱窗/私信转化"],
        "best_metric": "完播率 + 转粉率 + 关键词评论",
    }


def profile_checklist(topic: str) -> List[str]:
    return [
        f"主页一句话说明：专注{topic[:16]}相关的原创观点和实操清单。",
        "置顶 1 条介绍账号价值，置顶 1 条放资料领取说明，置顶 1 条放爆款代表作。",
        "评论区统一关键词，避免每条视频使用不同领取口令。",
        "资料包页面写清适用人群、边界和免责声明。",
    ]


def comment_templates(topic: str) -> List[str]:
    return [
        f"如果你也在经历“{topic[:20]}”，可以评论一个关键词，我用下一条继续拆。",
        "需要清单版可以评论“清单”，我会按平台规则整理成可保存版本。",
        "不同经历可以放评论区，我会挑高频问题做下一期。",
    ]


def monetization_risk_notes(script_text: str) -> List[str]:
    notes = ["不要承诺收益、疗效或确定结果，转化话术要留边界。"]
    if any(term in script_text for term in RISK_TERMS["health"]):
        notes.append("涉及健康/心理内容时，明确“不替代专业诊断或治疗”。")
    if any(term in script_text for term in RISK_TERMS["sexual"]):
        notes.append("涉及亲密关系或性相关内容时，避免羞辱化、猎奇化和引导站外违规交易。")
    return notes


def write_hook_analysis(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> Path:
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "hook-analysis.json"
    path.write_text(
        json.dumps(hook_analysis(script_text, duration, platforms), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def hook_analysis(script_text: str, duration: float, platforms: Iterable[str] | None = None) -> dict:
    hook_text = hook_seed_from_script(script_text)
    features = hook_features(hook_text)
    score = hook_score(features, hook_text, duration)
    selected = normalize_platforms(platforms)
    rewrites = {key: platform_hook_rewrites(PLATFORM_PRESETS[key], hook_text) for key in selected}
    return {
        "hook_text": hook_text,
        "score": score,
        "grade": hook_grade(score),
        "features": features,
        "recommendations": hook_recommendations(features, hook_text, duration),
        "platform_rewrites": rewrites,
    }


def hook_seed_from_script(script_text: str) -> str:
    compact = re.sub(r"\s+", " ", script_text).strip()
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?；;])", compact) if part.strip()]
    seed = "".join(parts[:2]) if parts else compact
    return seed[:72] or "本期观点"


def hook_features(hook_text: str) -> dict:
    return {
        "has_question": any(mark in hook_text for mark in ("为什么", "怎么", "吗", "？", "?")),
        "has_contrast": any(term in hook_text for term in ("不是", "其实", "反而", "真正", "但", "却", "别")),
        "has_audience": any(term in hook_text for term in ("你", "很多人", "新手", "普通人", "男人", "女人", "创作者")),
        "has_benefit": any(term in hook_text for term in ("学会", "看懂", "解决", "避开", "提高", "拿到", "变现", "涨粉")),
        "is_short": len(hook_text) <= 48,
        "has_specificity": any(char.isdigit() for char in hook_text) or any(term in hook_text for term in ("三", "3", "一个", "第", "这句")),
    }


def hook_score(features: dict, hook_text: str, duration: float) -> int:
    score = 35
    weights = {
        "has_question": 14,
        "has_contrast": 16,
        "has_audience": 12,
        "has_benefit": 13,
        "is_short": 10,
        "has_specificity": 8,
    }
    for key, weight in weights.items():
        if features.get(key):
            score += weight
    if len(hook_text) > 72:
        score -= 10
    if duration > 180:
        score -= 4
    return max(0, min(100, score))


def hook_grade(score: int) -> str:
    if score >= 82:
        return "强"
    if score >= 65:
        return "可用"
    return "待优化"


def hook_recommendations(features: dict, hook_text: str, duration: float) -> List[str]:
    recommendations: List[str] = []
    if not features.get("has_question"):
        recommendations.append("开头加一个明确问题，让用户知道为什么要继续看。")
    if not features.get("has_contrast"):
        recommendations.append("加入反差或纠偏表达，例如“真正的问题不是 X，而是 Y”。")
    if not features.get("has_audience"):
        recommendations.append("点名目标人群，例如“如果你也遇到这个问题”。")
    if not features.get("has_benefit"):
        recommendations.append("补一句看完收益，例如“看懂后就知道怎么调整”。")
    if not features.get("is_short"):
        recommendations.append("前三秒口播压到 48 个中文字符以内，避免信息过载。")
    if not features.get("has_specificity"):
        recommendations.append("加具体数字或场景，让钩子更像真实问题。")
    if duration > 180:
        recommendations.append("长视频建议前 15 秒补结构预告，降低跳出。")
    return recommendations or ["开头钩子基础完整，下一步重点测试封面和标题是否匹配。"]


def platform_hook_rewrites(preset: PlatformPreset, hook_text: str) -> List[str]:
    seed = title_seed_from_script(hook_text)
    if preset.key == "bilibili":
        rewrites = [
            f"为什么{seed}？这期用一个机制讲清楚。",
            f"很多人误会了{seed}，真正的问题在这里。",
            f"先别急着下结论，{seed}背后可能是另一套逻辑。",
        ]
    elif preset.key == "xiaohongshu":
        rewrites = [
            f"如果你也{seed}，先别急着自责。",
            f"关于{seed}，我想讲一个更真实的原因。",
            f"{seed}不是你的错，但你需要看懂它。",
        ]
    else:
        rewrites = [
            f"{seed}？先听完这 3 秒。",
            f"别再误会{seed}，真相可能反过来。",
            f"如果你也{seed}，这句话很重要。",
        ]
    return [rewrite[: preset.title_limit + 18] for rewrite in rewrites]


def write_title_experiments(project_dir: Path, script_text: str, duration: float, platforms: Iterable[str] | None = None) -> Path:
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "title-experiments.csv"
    rows = title_experiment_rows(script_text, duration, platforms)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TITLE_EXPERIMENT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def title_experiment_rows(script_text: str, duration: float, platforms: Iterable[str] | None = None) -> List[dict]:
    rows: List[dict] = []
    for key in normalize_platforms(platforms):
        preset = PLATFORM_PRESETS[key]
        metadata = platform_metadata(preset, script_text, duration)
        for index, title in enumerate(metadata["title_variants"], start=1):
            rows.append(
                {
                    "platform": key,
                    "platform_name": preset.name,
                    "variant_index": index,
                    "title": title,
                    "hypothesis": title_hypothesis(preset, index, title),
                    "selected": "yes" if index == 1 else "",
                    "publish_url": "",
                    "views": "",
                    "click_rate": "",
                    "notes": "",
                }
            )
    return rows


def title_hypothesis(preset: PlatformPreset, index: int, title: str) -> str:
    if preset.key == "bilibili":
        hypotheses = [
            "问题式标题验证搜索和首页推荐点击。",
            "反常识表达验证评论讨论和收藏。",
            "降低羞耻感表达验证用户共鸣。",
            "机制解释表达验证长视频完播。",
            "讲透型表达验证系列关注。",
        ]
    elif preset.key == "xiaohongshu":
        hypotheses = [
            "共情型标题验证收藏和评论倾诉。",
            "实话型标题验证停留和信任。",
            "人群代入标题验证封面点击。",
            "安抚加原因标题验证收藏。",
            "讲清楚标题验证搜索转化。",
        ]
    else:
        hypotheses = [
            "前三秒问题钩子验证停留。",
            "纠偏型标题验证评论互动。",
            "反转型标题验证完播。",
            "短利益点标题验证首屏点击。",
            "强提醒标题验证转粉。",
        ]
    return hypotheses[min(index - 1, len(hypotheses) - 1)]


def platform_metadata(preset: PlatformPreset, script_text: str, duration: float) -> dict:
    title_seed = title_seed_from_script(script_text)
    title = platform_title(preset, title_seed)
    risks = risk_checks(script_text)
    hashtags = platform_hashtags(preset, script_text)
    score, suggestions = traffic_score(preset, title, hashtags, risks, duration, script_text)
    return {
        "platform": asdict(preset),
        "title": title,
        "title_variants": title_variants(preset, title_seed),
        "cover_text": cover_text(preset, title_seed),
        "description": platform_description(preset, script_text),
        "hashtags": hashtags,
        "risk_checks": risks,
        "traffic_score": score,
        "improvement_suggestions": suggestions,
        "comment_prompt": comment_prompt(preset, title_seed),
        "conversion_cta": conversion_cta(preset),
        "duration_seconds": round(duration, 3),
        "technical_checklist": technical_checklist(preset),
        "traffic_checklist": traffic_checklist(preset),
    }


def title_seed_from_script(script_text: str) -> str:
    compact = re.sub(r"\s+", " ", script_text).strip()
    first = re.split(r"[。！？!?；;]", compact, maxsplit=1)[0].strip()
    return first[:36] or "本期观点"


def platform_title(preset: PlatformPreset, seed: str) -> str:
    if preset.key == "bilibili":
        title = f"为什么{seed}？一个更清醒的解释"
    elif preset.key == "xiaohongshu":
        title = f"{seed}，先别急着自责"
    else:
        title = f"{seed}？先听这句"
    return title[: preset.title_limit]


def title_variants(preset: PlatformPreset, seed: str) -> List[str]:
    if preset.key == "bilibili":
        variants = [
            f"为什么{seed}？一个更清醒的解释",
            f"{seed}背后，真正的问题可能不是你想的那样",
            f"别急着自责：{seed}的深层原因",
            f"从心理机制看懂：{seed}",
            f"{seed}，这期把逻辑讲透",
        ]
    elif preset.key == "xiaohongshu":
        variants = [
            f"{seed}，先别急着自责",
            f"关于{seed}，我想说句实话",
            f"如果你也{seed}，先看完这条",
            f"{seed}不是你的错，但要看懂原因",
            f"这条讲清楚{seed}",
        ]
    else:
        variants = [
            f"{seed}？先听这句",
            f"别再误会{seed}",
            f"{seed}，真相可能反过来",
            f"3 秒看懂{seed}",
            f"如果你也{seed}，一定听完",
        ]
    return [variant[: preset.title_limit] for variant in variants]


def cover_text(preset: PlatformPreset, seed: str) -> str:
    if preset.key == "bilibili":
        return f"{seed}\n真正的问题是什么"
    if preset.key == "xiaohongshu":
        return f"{seed[:18]}\n别再误解自己"
    return f"{seed[:14]}\n3秒说透"


def platform_description(preset: PlatformPreset, script_text: str) -> str:
    summary = re.sub(r"\s+", " ", script_text).strip()[:180]
    if preset.key == "bilibili":
        return f"{summary}\n\n本视频为原创观点口播，素材请使用原创或授权资源。欢迎在评论区补充经历和不同看法。"
    if preset.key == "xiaohongshu":
        return f"{summary}\n\n适合收藏后慢慢看。内容是个人观点整理，不替代专业建议。"
    return f"{summary}\n\n关注我，下一条继续拆这个问题。"


def comment_prompt(preset: PlatformPreset, seed: str) -> str:
    if preset.key == "bilibili":
        return f"你觉得“{seed}”更像个人问题，还是环境和习惯共同造成的？"
    if preset.key == "xiaohongshu":
        return f"你有没有类似“{seed}”的经历？可以只说感受，不用暴露隐私。"
    return f"你身边有没有人也遇到过“{seed}”？评论区说一个关键词。"


def conversion_cta(preset: PlatformPreset) -> str:
    if preset.key == "bilibili":
        return "适合做系列：结尾引导关注、收藏，并预告下一期的反常识观点。"
    if preset.key == "xiaohongshu":
        return "适合导向私域/咨询/资料包：先用收藏价值建立信任，再引导主页。"
    return "适合导向关注/直播/橱窗：结尾用下一条预告或领取资料引导转化。"


def platform_hashtags(preset: PlatformPreset, script_text: str) -> List[str]:
    tags = ["认知", "情绪", "关系", "自我成长"]
    if any(term in script_text for term in RISK_TERMS["sexual"]):
        tags.extend(["亲密关系", "男性成长"])
    if preset.key == "bilibili":
        tags.extend(["心理", "观点"])
    elif preset.key == "xiaohongshu":
        tags.extend(["成长笔记", "关系思考"])
    else:
        tags.extend(["情感", "成长"])
    deduped = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[: preset.tag_limit]


def risk_checks(script_text: str) -> List[dict]:
    checks = []
    for group, terms in RISK_TERMS.items():
        hits = [term for term in terms if term in script_text]
        if hits:
            checks.append(
                {
                    "type": group,
                    "hits": hits,
                    "action": "发布前人工复核，避免绝对化、羞辱化或未经证实的健康/心理断言。",
                }
            )
    return checks or [{"type": "none", "hits": [], "action": "未发现预置高风险词，仍需人工复核语境。"}]


def technical_checklist(preset: PlatformPreset) -> List[str]:
    return [
        f"导出比例: {preset.aspect_ratio}",
        f"建议尺寸: {preset.target_size}",
        "字幕已硬烧且位于安全区",
        "口播清晰，BGM 不盖过人声",
        "封面文字在手机端可读",
    ]


def traffic_checklist(preset: PlatformPreset) -> List[str]:
    if preset.key == "bilibili":
        return ["标题有问题钩子", "简介补充观点背景", "评论区设置讨论问题", "可归入系列/合集"]
    if preset.key == "xiaohongshu":
        return ["封面一句话能收藏", "标题避免过长", "正文有清单感", "结尾引导评论经历"]
    return ["前三秒直接抛冲突", "字幕短而大", "结尾引导关注下一条", "适合拆成系列"]


def traffic_score(
    preset: PlatformPreset,
    title: str,
    hashtags: Sequence[str],
    risks: Sequence[dict],
    duration: float,
    script_text: str,
) -> tuple[int, List[str]]:
    score = 100
    suggestions: List[str] = []
    if len(title) < 8:
        score -= 10
        suggestions.append("标题过短，建议补充明确冲突或收益点。")
    if len(title) > preset.title_limit:
        score -= 15
        suggestions.append("标题超过平台建议长度，需压缩。")
    if len(hashtags) < min(4, preset.tag_limit):
        score -= 8
        suggestions.append("标签偏少，建议补足主题词和人群词。")
    if any(check["type"] != "none" for check in risks):
        score -= 12
        suggestions.append("存在敏感或绝对化表达，发布前需要降噪和人工复核。")
    first_sentence = title_seed_from_script(script_text)
    if not any(mark in first_sentence for mark in ("为什么", "怎么", "别", "不是", "真正", "？", "?")):
        score -= 10
        suggestions.append("开头钩子不够强，建议改成问题、反常识或直接利益点。")
    if preset.key == "douyin" and duration > 90:
        score -= 12
        suggestions.append("抖音版本偏长，建议拆成 30-60 秒系列切片。")
    if preset.key == "xiaohongshu" and duration > 180:
        score -= 8
        suggestions.append("小红书版本偏长，建议拆成更强收藏感的短版。")
    if preset.key == "bilibili" and duration < 60:
        score -= 6
        suggestions.append("B 站版本偏短，建议补充结构化论证或系列导流。")
    if not suggestions:
        suggestions.append("当前发布包基础完整，可继续优化封面视觉和评论区引导。")
    return max(0, min(100, score)), suggestions


def render_platform_publish_markdown(metadata: dict) -> str:
    platform = metadata["platform"]
    lines = [
        f"# {platform['name']}发布包",
        "",
        f"- 标题: {metadata['title']}",
        f"- 封面文案: {metadata['cover_text']}",
        f"- 推荐比例: {platform['aspect_ratio']}",
        f"- 推荐尺寸: {platform['target_size']}",
        f"- 流量优化评分: {metadata['traffic_score']}/100",
        "",
        "## 简介",
        metadata["description"],
        "",
        "## 标题变体",
        *[f"- {title}" for title in metadata["title_variants"]],
        "",
        "## 标签",
        " ".join(f"#{tag}" for tag in metadata["hashtags"]),
        "",
        "## 评论区引导",
        metadata["comment_prompt"],
        "",
        "## 转化 CTA",
        metadata["conversion_cta"],
        "",
        "## 风险检查",
    ]
    for check in metadata["risk_checks"]:
        hits = "、".join(check["hits"]) if check["hits"] else "无"
        lines.append(f"- {check['type']}: {hits}；{check['action']}")
    lines.extend(["", "## 技术检查", *[f"- {item}" for item in metadata["technical_checklist"]]])
    lines.extend(["", "## 流量检查", *[f"- {item}" for item in metadata["traffic_checklist"]]])
    lines.extend(["", "## 优化建议", *[f"- {item}" for item in metadata["improvement_suggestions"]]])
    return "\n".join(lines) + "\n"


def render_cover_svg(metadata: dict) -> str:
    platform = metadata["platform"]
    width, height = [int(part) for part in platform["target_size"].split("x", 1)]
    is_vertical = height > width
    title_lines = cover_title_lines(metadata["cover_text"], is_vertical=is_vertical)
    longest = max(len(line) for line in title_lines)
    if is_vertical:
        font_size = max(48, min(84, int(height * 0.041), int(width / max(1, longest) * 0.58)))
    else:
        font_size = max(42, min(int(height * 0.055), int(width / max(1, longest) * 0.82)))
    line_height = int(font_size * 1.25)
    start_y = int(height * 0.40) - (len(title_lines) - 1) * line_height // 2
    text_nodes = []
    for index, line in enumerate(title_lines):
        text_nodes.append(
            f'<text data-role="cover-title" x="{width // 2}" y="{start_y + index * line_height}" text-anchor="middle" '
            f'font-size="{font_size}" font-weight="800" fill="#ffffff">{escape_xml(line)}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        f'  <rect width="{width}" height="{height}" fill="#101828"/>\n'
        f'  <rect x="{int(width * 0.06)}" y="{int(height * 0.08)}" width="{int(width * 0.88)}" '
        f'height="{int(height * 0.84)}" rx="28" fill="#126a5f"/>\n'
        f'  <text x="{width // 2}" y="{int(height * 0.18)}" text-anchor="middle" font-size="{max(32, int(height * 0.032))}" '
        f'font-weight="700" fill="#d9f99d">{escape_xml(platform["name"])}</text>\n'
        f'  {"".join(text_nodes)}\n'
        f'  <text x="{width // 2}" y="{int(height * 0.84)}" text-anchor="middle" font-size="{max(28, int(height * 0.028))}" '
        f'font-weight="600" fill="#ecfeff">原创口播 · 观点拆解</text>\n'
        "</svg>\n"
    )


def wrap_cover_text(text: str, max_chars: int) -> List[str]:
    cleaned = text.replace("\n", " ").strip()
    lines = []
    while cleaned:
        lines.append(cleaned[:max_chars])
        cleaned = cleaned[max_chars:].strip()
    return lines[:3] or ["本期观点"]


def cover_title_lines(text: str, is_vertical: bool) -> List[str]:
    if not is_vertical:
        return wrap_cover_text(text, max_chars=12)

    parts = [part.strip() for part in text.splitlines() if part.strip()]
    headline = parts[0] if parts else "本期观点"
    cta = parts[-1] if len(parts) > 1 else "3秒说透"
    headline_lines = wrap_cover_text(headline, max_chars=5)[:2]
    return [*headline_lines, cta[:5]]


def escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
