from __future__ import annotations

import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from workflow.platforms import write_platform_packages
from workflow.platforms import normalize_platforms


SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".docx"}
JIANying_CALM_MALE_VOICE = "jianying-calm-male"
EDGE_CALM_MALE_VOICE = "edge:zh-CN-YunyangNeural:rate=-6%:pitch=-2Hz"


@dataclass(frozen=True)
class SubtitleSegment:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class SelectedAssets:
    bgm: Optional[Path]
    images: List[Path]


@dataclass(frozen=True)
class ProjectResult:
    project_dir: Path
    script_path: Path
    srt_path: Path
    manifest_path: Path
    voice_command_path: Path


def load_text_document(path: Path) -> str:
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"文案文件不存在: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_TEXT_EXTENSIONS:
        raise ValueError(f"暂不支持 {source.suffix}，请先使用 .txt、.md 或 .docx")
    if suffix == ".docx":
        return _load_docx_text(source)
    text = source.read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _load_docx_text(source: Path) -> str:
    with zipfile.ZipFile(source) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs).strip()


def split_for_subtitles(text: str, max_chars: int = 28) -> List[str]:
    compact = re.sub(r"[ \t]+", " ", text.replace("\n", " ")).strip()
    if not compact:
        return []

    raw_parts = re.split(r"(?<=[。！？!?；;])", compact)
    parts: List[str] = []
    for raw_part in raw_parts:
        part = raw_part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = _find_cut(part, max_chars)
            parts.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            parts.append(part)
    return parts


def estimate_voice_timeline(
    text: str,
    chars_per_second: float = 4.8,
    max_chars: int = 28,
    min_segment_seconds: float = 1.2,
) -> List[SubtitleSegment]:
    if chars_per_second <= 0:
        raise ValueError("chars_per_second 必须大于 0")

    cursor = 0.0
    segments: List[SubtitleSegment] = []
    for index, part in enumerate(split_for_subtitles(text, max_chars=max_chars), start=1):
        duration = max(min_segment_seconds, len(part) / chars_per_second)
        end = cursor + duration
        segments.append(SubtitleSegment(index=index, start_seconds=cursor, end_seconds=end, text=part))
        cursor = end
    return segments


def render_srt(segments: Sequence[SubtitleSegment]) -> str:
    blocks = []
    for segment in segments:
        blocks.append(
            f"{segment.index}\n"
            f"{format_srt_time(segment.start_seconds)} --> {format_srt_time(segment.end_seconds)}\n"
            f"{segment.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def scale_segments_to_duration(
    segments: Sequence[SubtitleSegment],
    duration_seconds: float,
) -> List[SubtitleSegment]:
    if duration_seconds <= 0 or not segments:
        return list(segments)
    source_duration = segments[-1].end_seconds
    if source_duration <= 0:
        return list(segments)
    ratio = duration_seconds / source_duration
    scaled: List[SubtitleSegment] = []
    for segment in segments:
        scaled.append(
            SubtitleSegment(
                index=segment.index,
                start_seconds=segment.start_seconds * ratio,
                end_seconds=segment.end_seconds * ratio,
                text=segment.text,
            )
        )
    return scaled


def format_srt_time(seconds: float) -> str:
    milliseconds = int(math.ceil(seconds * 1000 - 1e-9))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def voice_output_path(voice_dir: Path, voice: str) -> Path:
    return voice_dir / ("voice.mp3" if voice.startswith("edge:") or voice == JIANying_CALM_MALE_VOICE else "voice.aiff")


def voice_command(text: str, voice: str, output: Path) -> List[str]:
    if voice == JIANying_CALM_MALE_VOICE:
        voice = EDGE_CALM_MALE_VOICE
    if voice.startswith("edge:"):
        _, edge_voice, rate, pitch = (voice.split(":", 3) + ["", "", "", ""])[:4]
        rate = rate.removeprefix("rate=")
        pitch = pitch.removeprefix("pitch=")
        return [
            "python3",
            "-m",
            "edge_tts",
            "--voice",
            edge_voice or "zh-CN-YunyangNeural",
            f"--rate={rate or '-6%'}",
            f"--pitch={pitch or '-2Hz'}",
            "--text",
            text,
            "--write-media",
            str(output),
        ]
    return ["say", "-v", voice, "-o", str(output), text]


def select_assets(bgm: Optional[Path], images: Iterable[Path]) -> SelectedAssets:
    bgm_path = _existing_path(bgm, "BGM") if bgm else None
    image_paths = [_existing_path(image, "图片") for image in images]
    return SelectedAssets(bgm=bgm_path, images=image_paths)


def build_project(
    root: Path,
    project_id: str,
    script_path: Path,
    voice: str,
    bgm: Optional[Path] = None,
    images: Optional[Iterable[Path]] = None,
    chars_per_second: float = 4.8,
    platforms: Optional[Iterable[str]] = None,
    target_duration_seconds: Optional[float] = None,
) -> ProjectResult:
    root = Path(root)
    project_dir = root / "projects" / project_id
    assets = select_assets(bgm=bgm, images=images or [])
    text = load_text_document(script_path)
    segments = estimate_voice_timeline(text, chars_per_second=chars_per_second)
    if target_duration_seconds and target_duration_seconds > 0:
        segments = scale_segments_to_duration(segments, target_duration_seconds)

    script_out = project_dir / "script.txt"
    exports_dir = project_dir / "exports"
    voice_dir = project_dir / "voice"
    bgm_dir = project_dir / "assets" / "bgm"
    image_dir = project_dir / "assets" / "images"

    for directory in (exports_dir, voice_dir, bgm_dir, image_dir):
        directory.mkdir(parents=True, exist_ok=True)

    script_out.write_text(text, encoding="utf-8")

    copied_bgm = _copy_optional(assets.bgm, bgm_dir)
    copied_images = [_copy_required(image, image_dir) for image in assets.images]

    srt_path = exports_dir / "subtitles.srt"
    srt_path.write_text(render_srt(segments), encoding="utf-8")

    voice_output = voice_output_path(voice_dir, voice)
    voice_cmd = voice_command(text, voice=voice, output=voice_output)
    voice_command_path = voice_dir / "generate_voice.sh"
    voice_command_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + _shell_join(voice_cmd) + "\n", encoding="utf-8")
    voice_command_path.chmod(0o755)

    manifest_path = project_dir / "episode.yaml"
    manifest_path.write_text(
        _episode_manifest(
            project_id=project_id,
            voice=voice,
            script_path=script_out,
            srt_path=srt_path,
            voice_output=voice_output,
            bgm=copied_bgm,
            images=copied_images,
            duration=segments[-1].end_seconds if segments else 0,
        ),
        encoding="utf-8",
    )

    _write_resolve_readme(project_dir, copied_bgm, copied_images)
    _write_asset_license_ledger(project_dir, copied_bgm, copied_images)
    duration = segments[-1].end_seconds if segments else 0
    _write_publish_checklist(project_dir, duration=duration)
    _write_performance_template(project_dir, platforms=platforms)
    write_platform_packages(project_dir, script_text=text, duration=duration, platforms=platforms)
    return ProjectResult(
        project_dir=project_dir,
        script_path=script_out,
        srt_path=srt_path,
        manifest_path=manifest_path,
        voice_command_path=voice_command_path,
    )


def _find_cut(text: str, max_chars: int) -> int:
    preferred = max(text.rfind(mark, 0, max_chars + 1) for mark in ("，", ",", "、", " "))
    if preferred >= max_chars // 2:
        return preferred + 1
    return max_chars


def _existing_path(path: Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"{label}文件不存在: {resolved}")
    return resolved


def _copy_optional(source: Optional[Path], target_dir: Path) -> Optional[Path]:
    return _copy_required(source, target_dir) if source else None


def _copy_required(source: Path, target_dir: Path) -> Path:
    target = target_dir / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    sidecar = source.with_name(f"{source.name}.source.json")
    if sidecar.exists():
        shutil.copy2(sidecar, target.with_name(f"{target.name}.source.json"))
    return target


def _shell_join(command: Sequence[str]) -> str:
    return " ".join("'" + item.replace("'", "'\\''") + "'" for item in command)


def _episode_manifest(
    project_id: str,
    voice: str,
    script_path: Path,
    srt_path: Path,
    voice_output: Path,
    bgm: Optional[Path],
    images: Sequence[Path],
    duration: float,
) -> str:
    image_lines = "\n".join(f"  - {image}" for image in images) if images else "  []"
    return (
        f"project_id: {project_id}\n"
        "workflow: local_video_workflow\n"
        "content_policy: original_authorized\n"
        f"voice: {voice}\n"
        f"estimated_duration_seconds: {duration:.3f}\n"
        f"script: {script_path}\n"
        f"subtitle_srt: {srt_path}\n"
        f"voice_output: {voice_output}\n"
        f"bgm: {bgm if bgm else ''}\n"
        "images:\n"
        f"{image_lines}\n"
    )


def _write_resolve_readme(project_dir: Path, bgm: Optional[Path], images: Sequence[Path]) -> None:
    image_list = "\n".join(f"- {image.name}" for image in images) if images else "- 暂未导入图片"
    bgm_text = bgm.name if bgm else "暂未导入 BGM"
    (project_dir / "README.md").write_text(
        "# DaVinci Resolve 导入说明\n\n"
        "1. 运行 `voice/generate_voice.sh` 生成口播音频。\n"
        "2. 在 Resolve 新建工程，导入 `voice/voice.*`、`exports/subtitles.srt`、`assets/images/` 和 BGM。\n"
        "3. 将口播音频放在 A1，字幕 SRT 导入字幕轨，图片按字幕段落节奏铺在 V1。\n"
        "4. BGM 降到约 -24 LUFS 附近，避免盖住口播。\n\n"
        f"## BGM\n{bgm_text}\n\n"
        f"## 图片\n{image_list}\n",
        encoding="utf-8",
    )


def _write_asset_license_ledger(project_dir: Path, bgm: Optional[Path], images: Sequence[Path]) -> None:
    rows = []
    if bgm:
        rows.append(("BGM", bgm.name, f"assets/bgm/{bgm.name}", _asset_source_note(bgm)))
    for image in images:
        rows.append(("图片", image.name, f"assets/images/{image.name}", _asset_source_note(image)))

    if rows:
        table = "\n".join(
            f"| {kind} | `{name}` | `{path}` | {source_note} | 待复核 |"
            for kind, name, path, source_note in rows
        )
    else:
        table = "| 暂无 | - | - | 待导入素材后补充 | 待复核 |"

    (project_dir / "assets" / "licenses.md").write_text(
        "# 素材授权台账\n\n"
        "发布到哔哩哔哩、小红书、抖音前，请补全每个素材的来源、授权范围和商用状态。\n\n"
        "| 类型 | 文件 | 项目路径 | 来源/授权 | 状态 |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{table}\n",
        encoding="utf-8",
    )


def _asset_source_note(path: Path) -> str:
    sidecar = path.with_name(f"{path.name}.source.json")
    if not sidecar.exists():
        return "待补充授权来源"
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "待补充授权来源"
    source = metadata.get("source") or "素材库"
    url = metadata.get("source_url") or ""
    return f"{source}: {url}" if url else str(source)


def _write_performance_template(project_dir: Path, platforms: Optional[Iterable[str]]) -> None:
    header = (
        "platform,status,publish_url,views,likes,comments,favorites,shares,followers_delta,"
        "conversion_notes,review_notes\n"
    )
    rows = [
        f"{platform},planned,,0,0,0,0,0,0,,\n"
        for platform in normalize_platforms(platforms)
    ]
    (project_dir / "exports" / "performance.csv").write_text(header + "".join(rows), encoding="utf-8")


def _write_publish_checklist(project_dir: Path, duration: float) -> None:
    (project_dir / "exports" / "publish-checklist.md").write_text(
        "# 发布前检查单\n\n"
        f"- 成片: `exports/preview.mp4`\n"
        f"- 字幕: `exports/subtitles.srt` 和硬字幕预览\n"
        f"- 估算时长: {duration:.1f} 秒\n"
        "- 素材来源: 原创或已授权\n"
        "- 健康、心理、性相关断言: 已标注来源或删除夸大表达\n\n"
        "## 哔哩哔哩\n"
        "- 标题保留问题钩子，但避免绝对化、羞辱化表述。\n"
        "- 封面需要清晰主题词、人物/场景或强视觉对比。\n"
        "- 简介写明原创口播、素材授权说明和必要免责声明。\n"
        "- 适合中长视频，可保留更完整论证链条。\n\n"
        "## 小红书\n"
        "- 需要短标题、封面大字和更强的个人经验/情绪入口。\n"
        "- 文案拆成 3-6 个可截图/可收藏的观点点。\n"
        "- 减少攻击性表达，突出真实体验、边界感和解决建议。\n\n"
        "## 抖音\n"
        "- 前 3 秒必须有问题、反常识或强情绪钩子。\n"
        "- 优先 9:16 竖版构图，字幕大而短，镜头节奏更快。\n"
        "- 需要导出短版切片，长口播应拆成系列。\n\n"
        "## 下一步待自动化\n"
        "- 平台比例导出: 16:9、9:16、1:1。\n"
        "- 标题/封面/标签生成与评分。\n"
        "- 平台敏感词和医疗健康声明检查。\n"
        "- 发布物料包: 标题、简介、标签、封面、视频、字幕。\n",
        encoding="utf-8",
    )
