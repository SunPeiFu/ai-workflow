from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote, unquote, urlparse

from workflow.bgm_library import bgm_source_catalog, download_bgm_from_url
from workflow.cli import align_project, audio_duration_seconds
from workflow.core import build_project
from workflow.platforms import PLATFORM_PRESETS, TITLE_EXPERIMENT_COLUMNS, hook_analysis, monetization_plan, publish_schedule, series_plan
from workflow.product_videos import is_product_payload, product_video_script, write_product_project_files
from workflow.remix import (
    analyze_remix_link,
    create_affiliate_jianying_handoff,
    create_affiliate_remix_plan,
    create_jianying_handoff,
    create_remix_package,
    find_jianying_app,
    list_llmstudio_models,
    optimize_copy_with_llmstudio,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
REFERENCE_VOICE_LABEL = "第1024期参考声音（中文口播）"
CAPCUT_CALM_MALE_LABEL = "剪映沉稳男声（同款参考）"
REFERENCE_VOICE_ENGINE = "Tingting"
CAPCUT_CALM_MALE_ENGINE = "jianying-calm-male"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PERFORMANCE_COLUMNS = [
    "platform",
    "status",
    "publish_url",
    "views",
    "likes",
    "comments",
    "favorites",
    "shares",
    "followers_delta",
    "conversion_notes",
    "review_notes",
]
PERFORMANCE_NUMBER_COLUMNS = {"views", "likes", "comments", "favorites", "shares", "followers_delta"}
TITLE_EXPERIMENT_NUMBER_COLUMNS = {"variant_index", "views"}
VIDEO_JOBS_LOCK = threading.Lock()
VIDEO_JOBS: set[str] = set()
JIANYING_AUTOMATION_LOCK = threading.Lock()
JIANYING_AUTOMATION_JOBS: Dict[str, Dict[str, Any]] = {}
DEFAULT_FFMPEG_THREADS = 2
MAX_TARGET_DURATION_SECONDS = 60 * 60
TARGET_VIDEO_BITRATE = "6000k"
TARGET_AUDIO_BITRATE = "160k"
TARGET_AUDIO_RATE = "44100"
REMIX_EDITABLE_SUFFIXES = {".txt", ".md", ".json", ".csv", ".srt", ".yaml", ".yml"}
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"


def create_project_from_payload(root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    project_id = _required_text(payload, "project_id")
    voice = resolve_voice_preset(payload.get("voice"))
    script_path = _script_path_from_payload(root, project_id, payload)
    bgm = _optional_path(payload.get("bgm"))
    images = [_optional_path(image) for image in payload.get("images", []) if str(image).strip()]
    platforms = payload.get("platforms") or None
    project = build_project(
        root=root,
        project_id=project_id,
        script_path=script_path,
        voice=voice,
        bgm=bgm,
        images=images,
        chars_per_second=float(payload.get("chars_per_second") or 4.8),
        platforms=platforms,
        target_duration_seconds=_target_duration_seconds(payload.get("target_duration_seconds")),
    )
    if is_product_payload(payload):
        write_product_project_files(project.project_dir, payload, project.script_path.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "project_id": project_id,
        "project_dir": str(project.project_dir),
        "script": str(project.script_path),
        "srt": str(project.srt_path),
        "manifest": str(project.manifest_path),
        "voice_command": str(project.voice_command_path),
    }


def save_uploaded_files(root: Path, content_type: str, body: bytes, kind: str = "files") -> Dict[str, Any]:
    if "multipart/form-data" not in content_type:
        return {"ok": False, "error": "请选择文件后再上传"}
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    upload_dir = root / "uploads" / safe_path_part(kind) / str(int(time.time() * 1000))
    upload_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for part in message.iter_parts():
        filename = part.get_filename()
        if not filename:
            continue
        target = unique_path(upload_dir / safe_filename(filename))
        target.write_bytes(part.get_payload(decode=True) or b"")
        files.append({"name": filename, "path": str(target)})
    if not files:
        return {"ok": False, "error": "没有收到可上传的文件"}
    return {"ok": True, "files": files}


def polish_remix_images_with_codex(root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_images = payload.get("images") or []
    images = [str(item.get("path") or item.get("url") or item) if isinstance(item, dict) else str(item) for item in raw_images]
    images = [image.strip() for image in images if image and image.strip()]
    prompt = str(payload.get("prompt") or "").strip()
    if not images:
        return {"ok": False, "error": "请选择需要 AI 润色的图片"}
    if not prompt:
        return {"ok": False, "error": "请先填写图片 AI 润色提示词"}
    codex = find_codex_cli()
    if not codex:
        return {"ok": False, "error": "未找到 Codex 客户端命令，请确认 Codex.app 已安装"}

    request_dir = root / "uploads" / "codex-image-polish" / str(int(time.time() * 1000))
    input_dir = request_dir / "inputs"
    output_dir = request_dir / "outputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    input_paths = prepare_codex_polish_inputs(root, images, input_dir)
    if not input_paths:
        return {"ok": False, "error": "选中的图片无法读取，请先上传为本地图片后重试"}

    task_prompt = codex_image_polish_prompt(prompt, output_dir, input_paths)
    (request_dir / "prompt.txt").write_text(task_prompt, encoding="utf-8")
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(request_dir),
        "--add-dir",
        str(output_dir),
    ]
    for image in input_paths:
        command.extend(["--image", str(image)])
    command.append("-")
    timed_out = False
    try:
        result = subprocess.run(command, text=True, input=task_prompt, capture_output=True, timeout=900, check=False)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = decode_subprocess_output(exc.output)
        stderr = decode_subprocess_output(exc.stderr)
        returncode = 124
    (request_dir / "codex-stdout.txt").write_text(stdout, encoding="utf-8")
    (request_dir / "codex-stderr.txt").write_text(stderr, encoding="utf-8")
    output_images = codex_polish_output_images(output_dir)
    if timed_out and output_images:
        return codex_polish_success_payload(root, request_dir, prompt, output_images, timed_out=True)
    if timed_out:
        return {
            "ok": False,
            "error": "Codex 图片润色超时，且未检测到已生成图片。建议减少选中图片数量，或把提示词写得更明确。",
            "request_dir": str(request_dir),
            "stdout": stdout[-1000:],
            "stderr": stderr[-1000:],
        }
    if returncode != 0:
        return codex_polish_failure_payload(request_dir, stdout, stderr)

    if not output_images:
        return {
            "ok": False,
            "error": "Codex 没有返回图片文件，请调整提示词后重试",
            "request_dir": str(request_dir),
            "stdout": stdout[-1000:],
        }
    return codex_polish_success_payload(root, request_dir, prompt, output_images, timed_out=False)


def polish_remix_images_locally(root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_images = payload.get("images") or []
    images = [str(item.get("path") or item.get("url") or item) if isinstance(item, dict) else str(item) for item in raw_images]
    images = [image.strip() for image in images if image and image.strip()]
    prompt = str(payload.get("prompt") or "").strip()
    if not images:
        return {"ok": False, "error": "请选择需要 AI 润色的图片"}
    if not prompt:
        return {"ok": False, "error": "请先填写图片 AI 润色提示词"}

    comfyui_url = str(payload.get("comfyui_url") or DEFAULT_COMFYUI_URL).rstrip("/")
    try:
        with urllib.request.urlopen(f"{comfyui_url}/system_stats", timeout=2) as response:
            response.read(1)
    except Exception as exc:
        return {
            "ok": False,
            "engine": "local",
            "error": f"本地润色需要先启动 ComfyUI 服务: {comfyui_url}。当前无法连接: {exc}",
        }

    workflow_path = Path(str(payload.get("workflow_path") or root / "workflow.local-image-polish.json")).expanduser()
    if not workflow_path.is_absolute():
        workflow_path = (root / workflow_path).resolve()
    if not workflow_path.exists():
        return {
            "ok": False,
            "engine": "local",
            "error": "本地 ComfyUI 已可连接，但还没有配置图片润色工作流文件 workflow.local-image-polish.json。",
            "comfyui_url": comfyui_url,
            "workflow_path": str(workflow_path),
        }

    return {
        "ok": False,
        "engine": "local",
        "error": "本地 ComfyUI 图片润色工作流入口已接入，下一步需要把 ComfyUI 工作流 JSON 映射为可执行队列。",
        "comfyui_url": comfyui_url,
        "workflow_path": str(workflow_path),
    }


def decode_subprocess_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def codex_polish_failure_payload(request_dir: Path, stdout: str, stderr: str) -> Dict[str, Any]:
    combined = "\n".join(part for part in [stderr, stdout] if part).strip()
    tail = combined[-1600:] if combined else ""
    lowered = combined.lower()
    if "stream disconnected" in lowered or "error sending request" in lowered or "responses_retry" in lowered:
        return {
            "ok": False,
            "error": "Codex 图片润色网络连接中断，未生成图片。请稍后重试，或切换为“本地润色”使用 ComfyUI。",
            "request_dir": str(request_dir),
            "retryable": True,
            "stderr": tail,
        }
    if "no prompt provided" in lowered:
        return {
            "ok": False,
            "error": "Codex 图片润色失败：Codex CLI 没有收到提示词输入，请重试。",
            "request_dir": str(request_dir),
            "retryable": True,
            "stderr": tail,
        }
    summary = tail or combined[:500] or "未知错误"
    return {
        "ok": False,
        "error": f"Codex 图片润色失败: {summary}",
        "request_dir": str(request_dir),
        "stderr": tail,
    }


def codex_polish_output_images(output_dir: Path) -> List[Path]:
    return sorted(path for path in output_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def codex_polish_success_payload(
    root: Path,
    request_dir: Path,
    prompt: str,
    output_images: List[Path],
    timed_out: bool = False,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "request_dir": str(request_dir),
        "prompt": prompt,
        "timed_out": timed_out,
        "images": [
            {
                "url": str(path),
                "path": str(path),
                "preview_url": generated_file_url(root, path),
                "selected": True,
            }
            for path in output_images
        ],
    }


def find_codex_cli() -> str:
    return shutil.which("codex") or (
        "/Applications/Codex.app/Contents/Resources/codex"
        if Path("/Applications/Codex.app/Contents/Resources/codex").exists()
        else ""
    )


def prepare_codex_polish_inputs(root: Path, images: List[str], input_dir: Path) -> List[Path]:
    input_paths = []
    for index, image in enumerate(images, start=1):
        value = str(image or "").strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            downloaded = download_xiaohongshu_image(value, input_dir, index)
            if downloaded:
                input_paths.append(downloaded)
            continue
        source = generated_request_path(root, value) if value.startswith("/generated/") else Path(value).expanduser()
        if not source.is_absolute():
            source = (root / value).resolve()
        if not source.exists() or source.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        target = unique_path(input_dir / f"{index:02d}-{safe_filename(source.name)}")
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        input_paths.append(target)
    return input_paths


def codex_image_polish_prompt(prompt: str, output_dir: Path, input_paths: List[Path]) -> str:
    names = "\n".join(f"- {index:02d}: {path.name}" for index, path in enumerate(input_paths, start=1))
    return (
        "你是本地视频工作流的产品宣传图生成执行器，不是简单修图脚本。\n"
        "Use case: ads-marketing / product-mockup。\n"
        "目标渠道：小红书/抖音/电商带货，用于图文笔记、短视频封面和商品种草主图。\n\n"
        "执行方式：\n"
        "1. 必须调用 Codex 的 imagegen skill 或可用的 AI 图片生成/编辑能力，以输入图片作为商品主体/包装参考来重新生成商业宣传图。\n"
        "2. 禁止只给原图增加边框、描边、相框、纯色底、简单滤镜、文字贴片或用 PIL/HTML/CSS 生成包装外壳来冒充 AI 润色。\n"
        "3. 如果当前运行环境没有真正的图片生成/编辑能力，不要生成低质量占位图；应直接失败并说明缺少 imagegen 能力。\n\n"
        "产品宣传图 brief：\n"
        "- 主体保真：保留商品主体、包装形状、颜色、可识别图案和关键文字，不改变商品品类，不捏造品牌。\n"
        "- 场景化背景：根据用户提示词重构背景和氛围，例如厨房台面、运动包旁、清爽饮品场景、浴室收纳、桌面开箱等。\n"
        "- 摄影级灯光：柔和主光、自然反光、干净阴影、高级质感、清晰细节，避免廉价过曝和塑料感。\n"
        "- 商业构图：商品占画面 45%-70%，主体清晰，背景有层次，保留适度留白，适合后续添加小红书标题或卖点贴纸。\n"
        "- 平台比例：优先生成 4:5 或 3:4 竖图；如果工具只能输出方图，也要确保主体居中且后续裁切到 4:5 不丢主体。\n"
        "- 风格方向：真实产品摄影、干净种草、轻电商主图、生活方式场景，不要赛博朋克、油画、卡通、过度梦幻。\n"
        "- 负面约束：不要边框，不要水印，不要乱码文字，不要新增虚假功效，不要改变包装关键信息，不要让主体变形。\n\n"
        "输出要求：\n"
        "1. 每张输入图都生成一张优化后的新产品宣传图，不要覆盖原图。\n"
        "2. 输出图片必须保存到下面的输出目录，命名为 polished-01.png、polished-02.png 这种格式。\n"
        "3. 不要只写说明，必须落盘生成图片文件。\n\n"
        f"输入图片：\n{names}\n\n"
        f"输出目录：{output_dir}\n\n"
        f"用户提示词：{prompt}\n"
    )


def generated_file_url(root: Path, path: Path) -> str:
    uploads_root = (root / "uploads").resolve()
    resolved = path.resolve()
    if not str(resolved).startswith(str(uploads_root)):
        return ""
    return "/generated/" + quote(str(resolved.relative_to(uploads_root)))


def generated_request_path(root: Path, request_path: str) -> Path:
    relative = unquote(request_path.removeprefix("/generated/"))
    return (root / "uploads" / relative).resolve()


def list_projects(root: Path) -> List[Dict[str, Any]]:
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return []
    projects: List[Dict[str, Any]] = []
    for project_dir in sorted((path for path in projects_dir.iterdir() if path.is_dir()), key=project_updated_at, reverse=True):
        projects.append(project_summary(root, project_dir))
    return projects


def delete_projects(root: Path, project_ids: List[str]) -> Dict[str, Any]:
    if not isinstance(project_ids, list):
        raise ValueError("project_ids 必须是数组")
    projects_root = (root / "projects").resolve()
    deleted = []
    missing = []
    invalid = []
    seen = set()

    for raw_project_id in project_ids:
        project_id = str(raw_project_id or "").strip()
        if not project_id or project_id in seen:
            continue
        seen.add(project_id)
        if Path(project_id).name != project_id:
            invalid.append(project_id)
            continue

        project_dir = (projects_root / project_id).resolve()
        if not str(project_dir).startswith(str(projects_root)) or not project_dir.is_dir():
            missing.append(project_id)
            continue

        shutil.rmtree(project_dir)
        deleted.append(project_id)

    return {"ok": True, "deleted": deleted, "missing": missing, "invalid": invalid}


def list_remix_packages(root: Path) -> Dict[str, Any]:
    packages_root = root / "remix_packages"
    if not packages_root.exists():
        return {"ok": True, "packages": [], "contents": []}
    prune_stale_remix_history_packages(root)
    packages = []
    for package_dir in sorted((path for path in packages_root.glob("*/*") if path.is_dir()), key=project_updated_at, reverse=True):
        files = []
        for file_path in sorted((path for path in package_dir.iterdir() if path.is_file()), key=lambda path: path.name):
            relative = file_path.relative_to(packages_root).as_posix()
            files.append(
                {
                    "name": file_path.name,
                    "path": relative,
                    "size": file_path.stat().st_size,
                    "editable": file_path.suffix.lower() in REMIX_EDITABLE_SUFFIXES,
                }
            )
        analysis = remix_package_analysis(package_dir)
        packages.append(
            {
                "name": package_dir.name,
                "group": package_dir.parent.name,
                "path": package_dir.relative_to(packages_root).as_posix(),
                "updated_at": int(project_updated_at(package_dir)),
                "source_url": analysis.get("url", ""),
                "title": ((analysis.get("copywriting") or {}).get("title") or package_dir.name),
                "platform": analysis.get("platform", ""),
                "files": files,
            }
        )
    return {"ok": True, "packages": packages, "contents": remix_contents_from_packages(packages)}


def prune_stale_remix_history_packages(root: Path) -> None:
    packages_root = root / "remix_packages"
    candidates: Dict[tuple[str, str], List[Path]] = {}
    for group in ("remix", "xiaohongshu-note", "douyin-note"):
        group_dir = packages_root / group
        if not group_dir.exists():
            continue
        for package_dir in group_dir.iterdir():
            if not package_dir.is_dir():
                continue
            analysis = remix_package_analysis(package_dir)
            source_url = str(analysis.get("url") or "").strip()
            if not source_url:
                continue
            candidates.setdefault((group, source_url), []).append(package_dir)
    for dirs in candidates.values():
        if len(dirs) <= 1:
            continue
        keep = max(dirs, key=project_updated_at)
        for package_dir in dirs:
            if package_dir != keep and package_dir.exists():
                shutil.rmtree(package_dir)


def remix_contents_from_packages(packages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for package in packages:
        source_url = package.get("source_url") or ""
        key_source = source_url or package.get("path", "")
        content_id = remix_content_id(key_source)
        item = grouped.setdefault(
            content_id,
            {
                "id": content_id,
                "source_url": source_url,
                "title": package.get("title") or package.get("name") or "未命名内容",
                "platform": package.get("platform") or "",
                "updated_at": package.get("updated_at") or 0,
                "package_count": 0,
                "file_count": 0,
                "packages": [],
            },
        )
        item["updated_at"] = max(int(item["updated_at"] or 0), int(package.get("updated_at") or 0))
        item["package_count"] += 1
        item["file_count"] += len(package.get("files") or [])
        item["packages"].append(package)
    return sorted(grouped.values(), key=lambda item: item["updated_at"], reverse=True)


def remix_content_id(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]


def remix_package_analysis(package_dir: Path) -> Dict[str, Any]:
    path = package_dir / "analysis.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("analysis"), dict):
        return data["analysis"]
    return data if isinstance(data, dict) else {}


def delete_remix_content(root: Path, content_id: str) -> Dict[str, Any]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == content_id), None)
    if not content:
        raise ValueError("内容不存在")
    packages_root = (root / "remix_packages").resolve()
    deleted = []
    for package in content.get("packages") or []:
        package_dir = (packages_root / package.get("path", "")).resolve()
        if str(package_dir).startswith(str(packages_root)) and package_dir.is_dir():
            shutil.rmtree(package_dir)
            deleted.append(package.get("path", ""))
    return {"ok": True, "id": content_id, "deleted": deleted}


def open_xiaohongshu_content_folder(root: Path, content_id: str) -> Dict[str, Any]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
    if not content:
        raise ValueError("内容不存在")

    packages = content.get("packages") or []
    package = next((item for item in packages if item.get("group") == "xiaohongshu-note"), None)
    if not package:
        package = preferred_xiaohongshu_source_package(packages)
    if not package:
        raise ValueError("当前项目没有可打开的小红书素材目录")

    packages_root = (root / "remix_packages").resolve()
    folder = (packages_root / str(package.get("path") or "")).resolve()
    if not str(folder).startswith(str(packages_root)) or folder == packages_root or not folder.is_dir():
        raise ValueError("小红书素材目录无效")

    opened_folder = subprocess.run(
        ["open", str(folder)],
        text=True,
        capture_output=True,
        check=False,
    ).returncode == 0
    if not opened_folder:
        raise RuntimeError("无法打开素材文件夹，请检查 Finder 是否可用")
    return {
        "ok": True,
        "content_id": content_id,
        "title": content.get("title") or "未命名内容",
        "package_group": package.get("group") or "",
        "folder": str(folder),
        "opened_folder": True,
        "message": "已在 Finder 中打开当前素材文件夹",
    }


def open_douyin_content_folder(root: Path, content_id: str) -> Dict[str, Any]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
    if not content:
        raise ValueError("内容不存在")
    packages = content.get("packages") or []
    package = next((item for item in packages if item.get("group") == "douyin-note"), None)
    if not package:
        package = preferred_douyin_source_package(packages)
    if not package:
        raise ValueError("当前项目没有可打开的抖音图文素材目录")

    packages_root = (root / "remix_packages").resolve()
    folder = (packages_root / str(package.get("path") or "")).resolve()
    if not str(folder).startswith(str(packages_root)) or folder == packages_root or not folder.is_dir():
        raise ValueError("抖音图文素材目录无效")
    opened_folder = subprocess.run(
        ["open", str(folder)],
        text=True,
        capture_output=True,
        check=False,
    ).returncode == 0
    if not opened_folder:
        raise RuntimeError("无法打开素材文件夹，请检查 Finder 是否可用")
    return {
        "ok": True,
        "content_id": content_id,
        "title": content.get("title") or "未命名内容",
        "package_group": package.get("group") or "",
        "folder": str(folder),
        "opened_folder": True,
        "message": "已在 Finder 中打开当前抖音图文素材文件夹",
    }


def start_jianying_content_generation(root: Path, content_id: str, launch: bool = True) -> Dict[str, Any]:
    content, package, package_dir = resolve_jianying_content_package(root, content_id)

    task_file = package_dir / "剪映生成任务.md"
    task_file.write_text(jianying_generation_task_markdown(content, package, package_dir), encoding="utf-8")

    app_path = find_jianying_app()
    launched = False
    opened_folder = False
    if launch:
        if app_path:
            launched = subprocess.run(["open", str(app_path)], text=True, capture_output=True, check=False).returncode == 0
        opened_folder = subprocess.run(["open", str(package_dir)], text=True, capture_output=True, check=False).returncode == 0

    message = "已准备剪映任务，并打开剪映与素材目录。" if launched else "已准备剪映任务。未检测到剪映启动成功，请手动打开剪映专业版。"
    return {
        "ok": True,
        "status": "ready_for_jianying",
        "content_id": content_id,
        "title": content.get("title") or "未命名内容",
        "source_url": content.get("source_url") or "",
        "package_group": package.get("group") or "",
        "package_dir": str(package_dir),
        "task_file": str(task_file),
        "jianying_app": str(app_path) if app_path else "",
        "launched": launched,
        "opened_folder": opened_folder,
        "message": message,
    }


def start_jianying_automation_job(root: Path, content_id: str, launch: bool = True) -> Dict[str, Any]:
    content, package, package_dir = resolve_jianying_content_package(root, content_id)
    job_id = hashlib.sha1(f"{content.get('id')}:{time.time()}".encode("utf-8")).hexdigest()[:16]
    job = {
        "ok": True,
        "job_id": job_id,
        "state": "queued",
        "progress": 0,
        "title": content.get("title") or "未命名内容",
        "package_dir": str(package_dir),
        "package_group": package.get("group") or "",
        "message": "等待启动剪映自动化",
        "steps": jianying_automation_steps(),
        "error": "",
    }
    with JIANYING_AUTOMATION_LOCK:
        JIANYING_AUTOMATION_JOBS[job_id] = job
    if launch:
        thread = threading.Thread(target=run_jianying_automation_job, args=(job_id, package_dir), daemon=True)
        thread.start()
    else:
        run_jianying_automation_job(job_id, package_dir, run_osascript=False)
    return {"ok": True, "job_id": job_id, "status": jianying_automation_job_status(job_id)}


def jianying_automation_job_status(job_id: str) -> Dict[str, Any]:
    with JIANYING_AUTOMATION_LOCK:
        job = JIANYING_AUTOMATION_JOBS.get(str(job_id or ""))
        if not job:
            raise ValueError("剪映自动化任务不存在")
        return json.loads(json.dumps(job, ensure_ascii=False))


def run_jianying_automation_job(job_id: str, package_dir: Path, run_osascript: bool = True) -> None:
    try:
        update_jianying_job(job_id, "running", 8, "准备剪映自动化载荷", step_id="prepare_payload")
        payload = prepare_jianying_automation_payload(package_dir)
        script_path = package_dir / "剪映UI自动化.applescript"
        script_path.write_text(jianying_ui_applescript(package_dir, payload.get("script_text", "")), encoding="utf-8")
        update_jianying_job(job_id, "running", 28, "已生成剪映自动化脚本", step_id="prepare_payload", step_state="completed")
        update_jianying_job(job_id, "running", 42, "准备启动剪映专业版", step_id="launch_jianying")
        if run_osascript:
            result = subprocess.run(["osascript", str(script_path)], text=True, capture_output=True, check=False, timeout=90)
            update_jianying_job_output(job_id, result.stdout.strip())
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "剪映 UI 自动化执行失败").strip())
            if "enteredEditor=true" not in result.stdout:
                raise RuntimeError(f"剪映没有进入编辑器界面: {result.stdout.strip()}")
        update_jianying_job(job_id, "running", 68, "已打开剪映并尝试进入创作界面", step_id="launch_jianying", step_state="completed")
        update_jianying_job(job_id, "running", 78, "已尝试点击开始创作", step_id="enter_creation", step_state="completed")
        update_jianying_job(job_id, "running", 84, "已尝试触发剪映脚本粗剪/SVIP智能入口", step_id="trigger_script_rough_cut", step_state="completed")
        update_jianying_job(job_id, "running", 88, "已打开素材包目录", step_id="open_package", step_state="completed")
        update_jianying_job(job_id, "running", 96, "已复制口播稿到剪贴板", step_id="copy_script", step_state="completed")
        update_jianying_job(job_id, "completed", 100, "剪映 UI 自动化准备完成，可在剪映中继续使用 SVIP 模板、智能字幕和音色生成视频")
    except Exception as exc:
        update_jianying_job(job_id, "failed", 100, "剪映 UI 自动化失败", error=str(exc))


def update_jianying_job(
    job_id: str,
    state: str,
    progress: int,
    message: str,
    step_id: str = "",
    step_state: str = "running",
    error: str = "",
) -> None:
    with JIANYING_AUTOMATION_LOCK:
        job = JIANYING_AUTOMATION_JOBS.get(job_id)
        if not job:
            return
        job["state"] = state
        job["progress"] = int(progress)
        job["message"] = message
        job["updated_at"] = int(time.time())
        if error:
            job["error"] = error
        if step_id:
            for step in job.get("steps", []):
                if step.get("id") == step_id:
                    step["state"] = step_state
                elif step_state == "completed" and step.get("state") == "pending":
                    break


def update_jianying_job_output(job_id: str, output: str) -> None:
    with JIANYING_AUTOMATION_LOCK:
        job = JIANYING_AUTOMATION_JOBS.get(job_id)
        if job is not None:
            job["automation_output"] = output


def jianying_automation_steps() -> List[Dict[str, str]]:
    return [
        {"id": "prepare_payload", "label": "准备素材与脚本", "state": "pending"},
        {"id": "launch_jianying", "label": "启动剪映专业版", "state": "pending"},
        {"id": "enter_creation", "label": "进入创作界面", "state": "pending"},
        {"id": "trigger_script_rough_cut", "label": "触发脚本粗剪/SVIP入口", "state": "pending"},
        {"id": "open_package", "label": "打开素材包目录", "state": "pending"},
        {"id": "copy_script", "label": "复制口播稿", "state": "pending"},
    ]


def resolve_jianying_content_package(root: Path, content_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Path]:
    content_id = str(content_id or "").strip()
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == content_id), None)
    if not content:
        raise ValueError("内容不存在")

    package = preferred_jianying_package(content.get("packages") or [])
    if not package:
        raise ValueError("该内容还没有可用于剪映生成的素材包，请先生成图文/视频包或剪映包")

    packages_root = (root / "remix_packages").resolve()
    package_dir = (packages_root / package.get("path", "")).resolve()
    if not str(package_dir).startswith(str(packages_root)) or not package_dir.is_dir():
        raise ValueError("素材包路径无效")
    return content, package, package_dir


def prepare_jianying_automation_payload(package_dir: Path) -> Dict[str, Any]:
    script_text = first_existing_text(package_dir, ["口播稿.txt", "文案.txt", "video-script.txt"])
    storyboard_text = first_existing_text(package_dir, ["分镜清单.md", "镜头清单.md", "image-package.md"])
    assets = []
    for path in sorted(package_dir.iterdir()):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mp3", ".m4a", ".wav"}:
            assets.append(str(path))
    payload = {
        "package_dir": str(package_dir),
        "script_text": script_text,
        "storyboard_text": storyboard_text,
        "asset_files": assets,
        "svip_features_to_use": ["模板成片", "智能字幕", "文本朗读/音色", "转场/BGM/特效"],
        "created_at": int(time.time()),
    }
    (package_dir / "jianying_automation_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def first_existing_text(package_dir: Path, names: List[str]) -> str:
    for name in names:
        path = package_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return ""


def jianying_ui_applescript(package_dir: Path, script_text: str) -> str:
    app_path = find_jianying_app()
    app_line = f'do shell script "open " & quoted form of "{app_path}"' if app_path else 'tell application "剪映专业版" to activate'
    escaped_script = script_text.replace("\\", "\\\\").replace('"', '\\"')
    return f'''
on waitForMainWindow()
  tell application "System Events"
    repeat 30 times
      if exists process "VideoFusion-macOS" then
        tell process "VideoFusion-macOS"
          try
            if exists window "剪映专业版" then return window "剪映专业版"
          end try
          try
            if (count of windows) > 0 then return window 1
          end try
        end tell
      end if
      delay 1
    end repeat
  end tell
  error "没有检测到剪映主窗口"
end waitForMainWindow

on elementExistsByNameOrDescription(targetText)
  tell application "System Events"
    tell process "VideoFusion-macOS"
      set targetWindow to my waitForMainWindow()
      repeat with itemRef in UI elements of targetWindow
        try
          if (name of itemRef as text) contains targetText then return true
        end try
        try
          if (description of itemRef as text) contains targetText then return true
        end try
      end repeat
    end tell
  end tell
  return false
end elementExistsByNameOrDescription

on clickElementByNameOrDescription(targetText)
  tell application "System Events"
    tell process "VideoFusion-macOS"
      set frontmost to true
      set targetWindow to my waitForMainWindow()
      repeat with itemRef in UI elements of targetWindow
        set matched to false
        try
          if (name of itemRef as text) contains targetText then set matched to true
        end try
        try
          if (description of itemRef as text) contains targetText then set matched to true
        end try
        if matched then
          try
            perform action "AXPress" of itemRef
            return true
          on error
            set itemPosition to position of itemRef
            set itemSize to size of itemRef
            click at {{(item 1 of itemPosition) + ((item 1 of itemSize) / 2), (item 2 of itemPosition) + ((item 2 of itemSize) / 2)}}
            return true
          end try
        end if
      end repeat
    end tell
  end tell
  return false
end clickElementByNameOrDescription

{app_line}
delay 4
set the clipboard to "{escaped_script}"
tell application "System Events"
  tell process "VideoFusion-macOS"
    set frontmost to true
    try
      click menu item "新建草稿" of menu 1 of menu bar item "文件" of menu bar 1
    end try
  end tell
end tell
delay 6
set enteredEditor to my elementExistsByNameOrDescription("MainMultiTimelineLayout")
if enteredEditor is false then
  set enteredEditor to my elementExistsByNameOrDescription("root_素材")
end if
set roughCutClicked to false
if enteredEditor is true then
  set roughCutClicked to my clickElementByNameOrDescription("scriptRoughCut")
end if
delay 2
do shell script "open " & quoted form of "{package_dir}"
return "enteredEditor=" & enteredEditor & ";scriptRoughCut=" & roughCutClicked
'''.strip()


def start_xiaohongshu_note_generation(root: Path, content_id: str, source_package_path: str = "") -> Dict[str, Any]:
    content, package, package_dir = resolve_xiaohongshu_source_package(root, content_id, source_package_path)
    analysis = remix_package_analysis(package_dir)
    copywriting = analysis.get("copywriting") or {}
    title = str(copywriting.get("title") or content.get("title") or "小红书图文笔记").strip()
    note_dir = root / "remix_packages" / "xiaohongshu-note" / f"{safe_path_part(title)[:40]}-小红书图文包"
    remove_existing_xiaohongshu_note_packages(root, content)
    if note_dir.exists():
        shutil.rmtree(note_dir)
    note_dir.mkdir(parents=True, exist_ok=True)

    note_body = xiaohongshu_note_body(package_dir, analysis, title)
    images = xiaohongshu_note_images(package_dir, analysis)
    local_images = materialize_xiaohongshu_note_images(note_dir, images)
    storyboard_images = [str(path) for path in local_images] or images
    tags = xiaohongshu_note_tags(copywriting.get("tags") or [])

    note_analysis = dict(analysis)
    note_analysis["platform"] = "xiaohongshu"
    note_analysis["copywriting"] = {
        "title": title,
        "body": note_body,
        "tags": [tag.lstrip("#") for tag in tags],
    }
    (note_dir / "analysis.json").write_text(json.dumps(note_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    (note_dir / "小红书笔记.md").write_text(xiaohongshu_note_markdown(title, note_body, tags), encoding="utf-8")
    (note_dir / "图片笔记分镜.md").write_text(xiaohongshu_image_storyboard_markdown(storyboard_images, title), encoding="utf-8")
    (note_dir / "发布清单.md").write_text(xiaohongshu_publish_checklist(), encoding="utf-8")
    (note_dir / "素材来源.md").write_text(xiaohongshu_asset_source_markdown(package, package_dir, images, storyboard_images), encoding="utf-8")

    return {
        "ok": True,
        "status": "ready_for_xiaohongshu",
        "content_id": content_id,
        "title": title,
        "source_url": content.get("source_url") or analysis.get("url", ""),
        "package_group": "xiaohongshu-note",
        "source_package_group": package.get("group") or "",
        "source_package_path": package.get("path") or "",
        "source_package_dir": str(package_dir),
        "note_dir": str(note_dir),
        "image_count": len(local_images),
        "image_dir": str(note_dir / "images"),
        "files": [str(path) for path in sorted(note_dir.iterdir()) if path.is_file()],
        "message": "已生成小红书图文笔记包，可复制笔记正文并按图片分镜发布。",
    }


def start_douyin_note_generation(root: Path, content_id: str, source_package_path: str = "") -> Dict[str, Any]:
    content, package, package_dir = resolve_douyin_source_package(root, content_id, source_package_path)
    analysis = remix_package_analysis(package_dir)
    copywriting = analysis.get("copywriting") or {}
    title = douyin_note_title(str(copywriting.get("title") or content.get("title") or "抖音图文").strip())
    body = douyin_note_body(str(copywriting.get("body") or "").strip(), title)
    tags = douyin_note_tags(copywriting.get("tags") or [])
    note_dir = root / "remix_packages" / "douyin-note" / f"{safe_path_part(title)[:40]}-抖音图文包"
    remove_existing_platform_note_packages(root, content, "douyin-note")
    if note_dir.exists():
        shutil.rmtree(note_dir)
    note_dir.mkdir(parents=True, exist_ok=True)

    images = douyin_note_images(package_dir, analysis)
    local_images = materialize_xiaohongshu_note_images(note_dir, images)
    ordered_images = [str(path) for path in local_images] or images
    note_analysis = dict(analysis)
    note_analysis["platform"] = "douyin"
    note_analysis["copywriting"] = {
        "title": title,
        "body": body,
        "tags": [tag.lstrip("#") for tag in tags],
    }
    note_analysis["images"] = [{"url": value} for value in ordered_images]
    (note_dir / "analysis.json").write_text(json.dumps(note_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    (note_dir / "抖音图文.md").write_text(douyin_note_markdown(title, body, tags), encoding="utf-8")
    (note_dir / "图片顺序.md").write_text(douyin_image_order_markdown(ordered_images, title), encoding="utf-8")
    (note_dir / "发布清单.md").write_text(douyin_publish_checklist(), encoding="utf-8")
    (note_dir / "素材来源.md").write_text(
        xiaohongshu_asset_source_markdown(package, package_dir, images, ordered_images),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "status": "ready_for_douyin",
        "content_id": content_id,
        "title": title,
        "source_url": content.get("source_url") or analysis.get("url", ""),
        "package_group": "douyin-note",
        "source_package_group": package.get("group") or "",
        "source_package_path": package.get("path") or "",
        "source_package_dir": str(package_dir),
        "note_dir": str(note_dir),
        "image_count": len(local_images),
        "image_dir": str(note_dir / "images"),
        "files": [str(path) for path in sorted(note_dir.iterdir()) if path.is_file()],
        "message": "已生成抖音图文包，可检查标题、图片顺序和商品挂载后发布。",
    }


def start_xiaohongshu_publish_assistant(root: Path, content_id: str, launch: bool = True) -> Dict[str, Any]:
    content, package, note_dir = resolve_xiaohongshu_note_package(root, content_id)
    note_path = note_dir / "小红书笔记.md"
    storyboard_path = note_dir / "图片笔记分镜.md"
    source_path = note_dir / "素材来源.md"
    if not note_path.exists():
        raise ValueError("小红书图文包缺少小红书笔记.md，请先重新生成图文包")
    note_text = note_path.read_text(encoding="utf-8").strip()
    storyboard_text = storyboard_path.read_text(encoding="utf-8").strip() if storyboard_path.exists() else ""
    source_text = source_path.read_text(encoding="utf-8").strip() if source_path.exists() else ""
    draft = parse_xiaohongshu_note_draft(note_text)
    storyboard_images = extract_xiaohongshu_storyboard_images(storyboard_text)
    image_files = ensure_xiaohongshu_publish_images(note_dir, storyboard_images)
    clipboard_text = xiaohongshu_publish_clipboard_text(draft["title"], draft["body"], draft["tags"], storyboard_text)
    payload = {
        "content_id": content_id,
        "title": draft["title"] or content.get("title") or package.get("title") or "小红书图文笔记",
        "body": draft["body"],
        "tags": draft["tags"],
        "note_dir": str(note_dir),
        "note_file": str(note_path),
        "storyboard_file": str(storyboard_path) if storyboard_path.exists() else "",
        "source_file": str(source_path) if source_path.exists() else "",
        "image_files": [str(path) for path in image_files],
        "image_count": len(image_files),
        "clipboard_text": clipboard_text,
        "source_text": source_text,
        "rednote_bundle_id": "com.xingin.discover",
        "publish_intent": "draft",
        "draft_intent": "image_note",
        "automation_level": "fill_draft_until_final_publish",
        "created_at": int(time.time()),
    }
    payload_path = note_dir / "xiaohongshu_draft_payload.json"
    legacy_payload_path = note_dir / "xiaohongshu_publish_payload.json"
    script_path = note_dir / "小红书发布助手.applescript"
    open_dir = note_dir
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    legacy_payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    script_path.write_text(
        xiaohongshu_publish_applescript(note_dir, open_dir, draft["title"], draft["body"], draft["tags"], image_files, clipboard_text),
        encoding="utf-8",
    )

    launched = False
    opened_folder = False
    script_output = ""
    if launch:
        try:
            result = subprocess.run(["osascript", str(script_path)], text=True, capture_output=True, check=False, timeout=30)
            launched = result.returncode == 0
            script_output = (result.stdout or result.stderr or "").strip()
        except subprocess.TimeoutExpired as exc:
            script_output = f"小红书自动化超时：{exc}"
        opened_folder = subprocess.run(["open", str(open_dir)], text=True, capture_output=True, check=False).returncode == 0

    return {
        "ok": True,
        "status": "ready_for_rednote",
        "content_id": content_id,
        "title": payload["title"],
        "package_group": "xiaohongshu-note",
        "note_dir": str(note_dir),
        "payload_file": str(payload_path),
        "script_file": str(script_path),
        "rednote_bundle_id": "com.xingin.discover",
        "image_count": len(image_files),
        "image_dir": str(note_dir / "images"),
        "opened_dir": str(open_dir),
        "draft_attempted": launch,
        "launched": launched,
        "opened_folder": opened_folder,
        "script_output": script_output,
        "message": "已唤起小红书 App，自动准备图片、标题、正文和标签，并打开当前图文包项目目录。",
    }


def resolve_xiaohongshu_note_package(root: Path, content_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Path]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
    if not content:
        raise ValueError("内容不存在")
    package = next((item for item in content.get("packages") or [] if item.get("group") == "xiaohongshu-note"), None)
    if not package:
        start_xiaohongshu_note_generation(root, content_id)
        listing = list_remix_packages(root)
        content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
        package = next((item for item in (content or {}).get("packages") or [] if item.get("group") == "xiaohongshu-note"), None)
    if not package:
        raise ValueError("小红书图文包生成失败")
    packages_root = (root / "remix_packages").resolve()
    note_dir = (packages_root / package.get("path", "")).resolve()
    if not str(note_dir).startswith(str(packages_root)) or not note_dir.is_dir():
        raise ValueError("小红书图文包路径无效")
    return content, package, note_dir


def resolve_xiaohongshu_source_package(root: Path, content_id: str, source_package_path: str = "") -> tuple[Dict[str, Any], Dict[str, Any], Path]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
    if not content:
        raise ValueError("内容不存在")
    package = None
    if source_package_path:
        package = next((item for item in content.get("packages") or [] if item.get("path") == source_package_path), None)
        if not package:
            raise ValueError("指定的小红书源素材包不属于当前内容，请重新生成图文包")
    else:
        package = preferred_xiaohongshu_source_package(content.get("packages") or [])
    if not package:
        raise ValueError("缺少可用于小红书图文生成的基础素材包")
    packages_root = (root / "remix_packages").resolve()
    package_dir = (packages_root / package.get("path", "")).resolve()
    if not str(package_dir).startswith(str(packages_root)) or not package_dir.is_dir():
        raise ValueError("小红书源素材包路径无效")
    return content, package, package_dir


def resolve_douyin_source_package(root: Path, content_id: str, source_package_path: str = "") -> tuple[Dict[str, Any], Dict[str, Any], Path]:
    listing = list_remix_packages(root)
    content = next((item for item in listing.get("contents", []) if item.get("id") == str(content_id or "")), None)
    if not content:
        raise ValueError("内容不存在")
    packages = content.get("packages") or []
    if source_package_path:
        package = next((item for item in packages if item.get("path") == source_package_path), None)
        if not package:
            raise ValueError("指定的抖音源素材包不属于当前内容")
    else:
        package = preferred_douyin_source_package(packages)
    if not package:
        raise ValueError("缺少可用于抖音图文生成的素材包")
    packages_root = (root / "remix_packages").resolve()
    package_dir = (packages_root / str(package.get("path") or "")).resolve()
    if not str(package_dir).startswith(str(packages_root)) or not package_dir.is_dir():
        raise ValueError("抖音源素材包路径无效")
    return content, package, package_dir


def remove_existing_xiaohongshu_note_packages(root: Path, content: Dict[str, Any]) -> None:
    remove_existing_platform_note_packages(root, content, "xiaohongshu-note")


def remove_existing_platform_note_packages(root: Path, content: Dict[str, Any], group: str) -> None:
    packages_root = (root / "remix_packages").resolve()
    for package in content.get("packages") or []:
        if package.get("group") != group:
            continue
        package_dir = (packages_root / package.get("path", "")).resolve()
        if str(package_dir).startswith(str(packages_root)) and package_dir.is_dir():
            shutil.rmtree(package_dir)


def parse_xiaohongshu_note_draft(note_text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current = ""
    for raw_line in note_text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    title = "\n".join(sections.get("标题") or []).strip()
    body_lines = sections.get("正文") or []
    body = "\n".join(body_lines).strip()
    tags = "\n".join(sections.get("标签") or []).strip()
    if not title:
        title = first_nonempty_markdown_line(note_text, fallback="小红书图文笔记")
    if not body:
        body = note_text.strip()
    return {
        "title": title,
        "body": body,
        "tags": normalize_xiaohongshu_tag_text(tags),
    }


def first_nonempty_markdown_line(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        value = line.strip().lstrip("#").strip()
        if value:
            return value
    return fallback


def normalize_xiaohongshu_tag_text(text: str) -> str:
    tags = []
    for part in text.replace("\n", " ").replace(",", " ").replace("，", " ").split():
        value = part.strip()
        if not value:
            continue
        value = value if value.startswith("#") else f"#{value}"
        tags.append(value)
    return " ".join(dict.fromkeys(tags))


def extract_xiaohongshu_storyboard_images(storyboard_text: str) -> List[str]:
    images = []
    for line in storyboard_text.splitlines():
        value = line.strip()
        if "素材：" not in value:
            continue
        image = value.split("素材：", 1)[1].strip()
        if image:
            images.append(image)
    return list(dict.fromkeys(images))


def ensure_xiaohongshu_publish_images(note_dir: Path, images: List[str]) -> List[Path]:
    image_dir = note_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    local_paths: List[Path] = []
    for index, image in enumerate(images, start=1):
        value = str(image or "").strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            downloaded = download_xiaohongshu_image(value, image_dir, index)
            if downloaded:
                local_paths.append(downloaded)
            continue
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            local_paths.append(candidate.resolve())
    if images or local_paths:
        return list(dict.fromkeys(local_paths))
    for image in sorted(image_dir.iterdir()):
        if image.is_file() and image.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            local_paths.append(image.resolve())
    return local_paths


def download_xiaohongshu_image(url: str, image_dir: Path, index: int) -> Path | None:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".jpg"
    target = image_dir / f"{index:02d}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return target.resolve()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            target.write_bytes(response.read())
        return target.resolve() if target.exists() and target.stat().st_size > 0 else None
    except Exception:
        return None


def materialize_xiaohongshu_note_images(note_dir: Path, images: List[str]) -> List[Path]:
    image_dir = note_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    local_paths: List[Path] = []
    for index, image in enumerate(images, start=1):
        value = str(image or "").strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            downloaded = download_xiaohongshu_image(value, image_dir, index)
            if downloaded:
                local_paths.append(downloaded)
            continue
        source = Path(value).expanduser()
        if source.exists() and source.is_file() and source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            target = unique_path(image_dir / f"{index:02d}-{safe_filename(source.name)}")
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            local_paths.append(target.resolve())
    return list(dict.fromkeys(local_paths))


def xiaohongshu_publish_clipboard_text(title: str, body: str, tags: str, storyboard_text: str) -> str:
    parts = [title.strip(), body.strip(), tags.strip()]
    if storyboard_text.strip():
        parts.extend(["——", "图片选择参考：", storyboard_text.strip()])
    return "\n\n".join(part for part in parts if part).strip()


def xiaohongshu_publish_applescript(note_dir: Path, open_dir: Path, title: str, body: str, tags: str, image_files: List[Path], clipboard_text: str) -> str:
    escaped_title = applescript_string(title)
    escaped_body = applescript_string(body)
    escaped_tags = applescript_string(tags)
    escaped_text = clipboard_text.replace("\\", "\\\\").replace('"', '\\"')
    image_aliases = ", ".join(f'POSIX file "{applescript_string(str(path))}"' for path in image_files)
    image_clipboard = f"set imageFiles to {{{image_aliases}}}" if image_aliases else "set imageFiles to {}"
    return f'''
on uiText(elementRef)
  set values to {{}}
  try
    set end of values to name of elementRef as text
  end try
  try
    set end of values to description of elementRef as text
  end try
  try
    set end of values to value of elementRef as text
  end try
  try
    set end of values to role of elementRef as text
  end try
  set AppleScript's text item delimiters to " "
  return values as text
end uiText

on clickFirstMatchingControl(candidateNames)
  tell application "System Events"
    if exists process "discover" then
      tell process "discover"
        if not (exists window 1) then return ""
        repeat with candidateName in candidateNames
          set shallowElements to (buttons of window 1) & (UI elements of window 1) & (static texts of window 1)
          repeat with elementRef in shallowElements
            try
              set labelText to my uiText(elementRef)
              if labelText contains (candidateName as text) then
                click elementRef
                return candidateName as text
              end if
            end try
          end repeat
        end repeat
      end tell
    end if
  end tell
  return ""
end clickFirstMatchingControl

on pasteIntoMatchingInput(candidateNames, textValue)
  if textValue is "" then return ""
  tell application "System Events"
    if exists process "discover" then
      tell process "discover"
        if not (exists window 1) then return ""
        repeat with candidateName in candidateNames
          set shallowInputs to (text fields of window 1) & (text areas of window 1) & (UI elements of window 1)
          repeat with elementRef in shallowInputs
            try
              set labelText to my uiText(elementRef)
              if labelText contains (candidateName as text) then
                click elementRef
                delay 0.2
                set the clipboard to textValue
                keystroke "v" using command down
                return candidateName as text
              end if
            end try
          end repeat
        end repeat
      end tell
    end if
  end tell
  return ""
end pasteIntoMatchingInput

on pasteImagesIntoFocusedArea()
  {image_clipboard}
  if (count of imageFiles) is 0 then return "no_images"
  set the clipboard to imageFiles
  tell application "System Events"
    if exists process "discover" then
      tell process "discover"
        set frontmost to true
        delay 0.2
        keystroke "v" using command down
      end tell
    end if
  end tell
  return "images_clipboard_pasted"
end pasteImagesIntoFocusedArea

on clickWindowRatio(xRatio, yRatio, fallbackLabel)
  tell application "System Events"
    if exists process "discover" then
      tell process "discover"
        if not (exists window 1) then return ""
        set p to position of window 1
        set s to size of window 1
        set targetX to (item 1 of p) + ((item 1 of s) * xRatio)
        set targetY to (item 2 of p) + ((item 2 of s) * yRatio)
        click at {{targetX, targetY}}
        return fallbackLabel
      end tell
    end if
  end tell
  return ""
end clickWindowRatio

set the clipboard to "{escaped_text}"
do shell script "open -b com.xingin.discover"
delay 3
tell application "System Events"
  if exists process "discover" then
    tell process "discover"
      set frontmost to true
    end tell
  end if
end tell
set clickedEntry to my clickFirstMatchingControl({{"发笔记", "创作", "加号", "Plus", "+"}})
if clickedEntry is "" then set clickedEntry to my clickWindowRatio(0.5, 0.96, "bottom_plus_coordinate")
delay 2
set clickedResume to my clickFirstMatchingControl({{"去编辑", "继续编辑", "编辑草稿"}})
if clickedResume is "" then set clickedResume to my clickWindowRatio(0.65, 0.78, "resume_draft_coordinate")
delay 1
set clickedImage to my clickFirstMatchingControl({{"图文", "图片", "相册", "照片", "Photo", "Image", "上传"}})
if clickedImage is "" then set clickedImage to my clickWindowRatio(0.5, 0.68, "image_area_coordinate")
delay 1
set pastedImages to my pasteImagesIntoFocusedArea()
delay 2
set clickedNext to my clickFirstMatchingControl({{"下一步", "继续", "完成", "Next", "Done"}})
if clickedNext is "" then set clickedNext to my clickWindowRatio(0.88, 0.08, "next_coordinate")
delay 2
set pastedTitle to my pasteIntoMatchingInput({{"标题", "添加标题", "请输入标题", "Title"}}, "{escaped_title}")
if pastedTitle is "" then
  set titleFallback to my clickWindowRatio(0.5, 0.34, "title_coordinate")
  tell application "System Events"
    tell process "discover"
      set the clipboard to "{escaped_title}"
      keystroke "v" using command down
    end tell
  end tell
  set pastedTitle to titleFallback
end if
set pastedBody to my pasteIntoMatchingInput({{"正文", "内容", "描述", "分享", "这一刻", "请输入正文", "Description"}}, "{escaped_body}")
if pastedBody is "" then
  set bodyFallback to my clickWindowRatio(0.5, 0.48, "body_coordinate")
  tell application "System Events"
    tell process "discover"
      set the clipboard to "{escaped_body}\n\n{escaped_tags}"
      keystroke "v" using command down
    end tell
  end tell
  set pastedBody to bodyFallback
end if
set pastedTags to my pasteIntoMatchingInput({{"标签", "话题", "Tag", "Topic"}}, "{escaped_tags}")
if pastedTitle is "" and pastedBody is "" then
  tell application "System Events"
    if exists process "discover" then
      tell process "discover"
        set frontmost to true
        set the clipboard to "{escaped_title}"
        keystroke "v" using command down
        key code 48
        set the clipboard to "{escaped_body}\n\n{escaped_tags}"
        keystroke "v" using command down
      end tell
    end if
  end tell
end if
return "rednote_opened=true;draft_entry=" & clickedEntry & ";resume=" & clickedResume & ";image_entry=" & clickedImage & ";image_paste=" & pastedImages & ";next=" & clickedNext & ";title=" & pastedTitle & ";body=" & pastedBody & ";tags=" & pastedTags & ";opened_dir={applescript_string(str(open_dir))};final_publish=manual"
'''.strip()


def applescript_string(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def xiaohongshu_note_body(package_dir: Path, analysis: Dict[str, Any], title: str) -> str:
    existing = first_existing_text(package_dir, ["小红书种草版.md", "copywriting.md", "文案.txt", "video-script.txt"])
    if existing:
        return existing
    copywriting = analysis.get("copywriting") or {}
    body = str(copywriting.get("body") or "").strip()
    if body:
        return body
    return f"{title}\n\n这条笔记基于已有素材包整理，发布前请补充真实使用体验、商品参数和授权图片。"


def xiaohongshu_note_images(package_dir: Path, analysis: Dict[str, Any]) -> List[str]:
    images = []
    for image in analysis.get("images") or []:
        if isinstance(image, dict):
            value = str(image.get("url") or image.get("path") or "").strip()
        else:
            value = str(image or "").strip()
        if value:
            images.append(normalize_xiaohongshu_image_reference(value))
    if images:
        return list(dict.fromkeys(images))
    for path in sorted(package_dir.iterdir()):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            images.append(str(path.resolve()))
    return list(dict.fromkeys(images))


def normalize_xiaohongshu_image_reference(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if urlparse(text).scheme in {"http", "https"}:
        return text
    path = Path(text).expanduser()
    if path.exists():
        return str(path.resolve())
    return text


def xiaohongshu_note_tags(tags: List[Any]) -> List[str]:
    cleaned = []
    for tag in tags:
        value = str(tag or "").strip().lstrip("#")
        if value:
            cleaned.append(f"#{value}")
    defaults = ["#好物分享", "#小红书种草", "#日常分享"]
    return list(dict.fromkeys(cleaned + defaults))[:8]


def douyin_note_title(title: str) -> str:
    value = str(title or "").replace("#", "").strip()
    for phrase in ("一篇帮你讲清楚", "一篇看懂", "保姆级攻略", "建议收藏"):
        value = value.replace(phrase, "")
    value = re.sub(r"\s+", " ", value).strip(" ｜|，,。.!！?？")
    return (value[:28].rstrip("，,。.!！?？") if len(value) > 28 else value) or "这份选择建议别错过"


def douyin_note_body(body: str, title: str) -> str:
    value = re.sub(r"\n{3,}", "\n\n", str(body or "").strip()).replace("小红书", "抖音")
    if not value:
        value = f"{title}。先看核心差异，再按自己的使用场景选择。"
    if len(value) > 280:
        value = value[:280].rstrip("，,。.!！?？") + "。"
    if not re.search(r"[？?]$", value):
        value = f"{value}\n\n你选产品时最看重哪一点？"
    return value


def douyin_note_tags(tags: List[Any]) -> List[str]:
    cleaned = []
    for tag in tags:
        value = str(tag or "").strip().lstrip("#")
        if value:
            cleaned.append(f"#{value}")
    return list(dict.fromkeys(cleaned + ["#抖音图文"]))[:5]


def douyin_note_images(package_dir: Path, analysis: Dict[str, Any]) -> List[str]:
    image_dir = package_dir / "images"
    if image_dir.is_dir():
        local_images = [
            str(path.resolve())
            for path in sorted(image_dir.iterdir())
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        if local_images:
            return local_images
    return xiaohongshu_note_images(package_dir, analysis)


def douyin_note_markdown(title: str, body: str, tags: List[str]) -> str:
    return (
        "# 抖音图文发布文案\n\n"
        f"## 标题\n{title}\n\n"
        f"## 正文\n{body}\n\n"
        f"## 标签\n{' '.join(tags)}\n"
    )


def douyin_image_order_markdown(images: List[str], title: str) -> str:
    roles = ["痛点或结果封面", "核心差异", "商品卖点", "使用场景", "细节对比", "选择建议", "互动收尾"]
    lines = ["# 抖音图片顺序", "", f"封面标题：{title}", ""]
    for index, image in enumerate(images, start=1):
        lines.append(f"{index}. {roles[min(index - 1, len(roles) - 1)]}")
        lines.append(f"   素材：{image}")
    if not images:
        lines.append("- 暂无图片，请回到素材拆解页补充商品图片。")
    return "\n".join(lines).strip() + "\n"


def douyin_publish_checklist() -> str:
    return """# 抖音图文发布清单

- [ ] 封面在首屏直接展示商品、痛点或结果
- [ ] 每张图片承担不同信息，不重复堆叠同一画面
- [ ] 清理小红书水印、界面截图和平台专属措辞
- [ ] 标题、正文和图片中的商品信息保持一致
- [ ] 删除绝对化、医疗功效和无法证明的宣传词
- [ ] 检查商品锚点或橱窗商品与素材一致
- [ ] 发布前人工确认图片顺序、价格和活动信息
"""


def xiaohongshu_note_markdown(title: str, body: str, tags: List[str]) -> str:
    return (
        "# 小红书笔记\n\n"
        f"## 标题\n{title}\n\n"
        f"## 正文\n{body}\n\n"
        "## 带货承接\n"
        "- 商品位：发布前填入要承接的商品名称、价格区间、规格和购买入口。\n"
        "- 转化话术：如果你也在找同类好物，可以先收藏这篇，再按自己的场景对照选择。\n"
        "- 素材要求：商品图、使用图、对比图优先用自有或授权素材，不直接搬运原视频截图。\n\n"
        f"## 标签\n{' '.join(tags)}\n"
    )


def xiaohongshu_image_storyboard_markdown(images: List[str], title: str) -> str:
    rows = ["# 图片笔记分镜\n"]
    if not images:
        rows.extend(
            [
                "- 图 1：封面图，突出标题关键词和核心卖点。\n",
                "- 图 2：细节图，展示材质、尺寸、使用场景。\n",
                "- 图 3：对比图，展示适合/不适合人群。\n",
            ]
        )
    else:
        for index, image in enumerate(images, start=1):
            if index == 1:
                purpose = f"封面图：叠加短标题「{title[:18]}」"
            elif index == 2:
                purpose = "细节图：展示商品/场景关键细节"
            else:
                purpose = "补充图：展示使用场景、对比或注意事项"
            rows.append(f"- 图 {index}：{purpose}\n  - 素材：{image}\n")
    return "".join(rows)


def xiaohongshu_publish_checklist() -> str:
    return (
        "# 小红书发布清单\n\n"
        "- 标题不带夸大承诺，不写绝对化词。\n"
        "- 图片优先使用自有或授权素材，不直接搬运原视频截图。\n"
        "- 正文保留真实体验感，避免明显 AI 口吻。\n"
        "- 商品承接信息必须人工确认：商品名称、规格、价格、佣金/橱窗链接和售后风险。\n"
        "- 带货转化不要硬插，正文先解决场景问题，再自然引导收藏、评论或点商品入口。\n"
        "- 标签围绕同一领域扩展，不堆无关热词。\n"
        "- 发布前检查商品价格、链接、规格和平台违禁词。\n"
    )


def xiaohongshu_asset_source_markdown(package: Dict[str, Any], package_dir: Path, images: List[str], local_images: List[str] | None = None) -> str:
    rows = [
        "# 素材来源\n\n",
        f"- 来源素材包：{packageGroupName(package.get('group') or '')} · `{package_dir}`\n",
        "- 授权要求：仅使用自有、授权或可商用素材；不要直接搬运原视频画面。\n\n",
        "## 原始图片素材\n",
    ]
    rows.extend(f"- {image}\n" for image in images)
    if local_images:
        rows.append("\n## 本地图文包图片\n")
        rows.extend(f"- {image}\n" for image in local_images)
    return "".join(rows)


def preferred_jianying_package(packages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    priority = {"affiliate-jianying": 0, "jianying": 1, "remix": 2}
    valid_packages = [package for package in packages if package.get("path")]
    if not valid_packages:
        return None
    return sorted(valid_packages, key=lambda package: (priority.get(package.get("group"), 9), -(int(package.get("updated_at") or 0))))[0]


def preferred_xiaohongshu_source_package(packages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    priority = {"remix": 0, "affiliate-jianying": 1, "jianying": 2}
    valid_packages = [package for package in packages if package.get("path") and package.get("group") != "xiaohongshu-note"]
    if not valid_packages:
        return None
    return sorted(valid_packages, key=lambda package: (priority.get(package.get("group"), 9), -(int(package.get("updated_at") or 0))))[0]


def preferred_douyin_source_package(packages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    priority = {"xiaohongshu-note": 0, "remix": 1, "affiliate-jianying": 2, "jianying": 3}
    valid_packages = [package for package in packages if package.get("path") and package.get("group") != "douyin-note"]
    if not valid_packages:
        return None
    return sorted(valid_packages, key=lambda package: (priority.get(package.get("group"), 9), -(int(package.get("updated_at") or 0))))[0]


def jianying_generation_task_markdown(content: Dict[str, Any], package: Dict[str, Any], package_dir: Path) -> str:
    files = sorted(path.name for path in package_dir.iterdir() if path.is_file())
    recommended = [name for name in files if name in {
        "口播稿.txt",
        "分镜清单.md",
        "文案.txt",
        "镜头清单.md",
        "抖音橱窗版.md",
        "小红书种草版.md",
        "剪映SVIP执行清单.md",
        "判重检查.md",
        "素材占位说明.md",
    }]
    file_lines = "\n".join(f"- `{name}`" for name in recommended or files)
    return (
        "# 剪映生成任务\n\n"
        f"- 内容标题：{content.get('title') or '未命名内容'}\n"
        f"- 来源链接：{content.get('source_url') or '无'}\n"
        f"- 素材包类型：{packageGroupName(package.get('group') or '')}\n"
        f"- 素材目录：`{package_dir}`\n\n"
        "## 建议导入文件\n"
        f"{file_lines}\n\n"
        "## 剪映执行步骤\n"
        "1. 新建 `9:16` 竖屏项目，导入本目录中的自有或授权素材。\n"
        "2. 将 `口播稿.txt` 或 `文案.txt` 作为旁白脚本，选择剪映里适合带货的中文口播音色生成语音。\n"
        "3. 根据 `分镜清单.md` / `镜头清单.md` 重排镜头，不复用原视频画面顺序。\n"
        "4. 使用剪映智能字幕生成字幕，并统一检查错字、商品风险词和平台违禁词。\n"
        "5. 替换 BGM、封面、字幕样式、转场和口播音色后导出 `1080x1920 MP4`。\n\n"
        "## 判重提醒\n"
        "- 不要直接搬运原视频画面、原声音、原字幕样式和原镜头顺序。\n"
        "- 商品卖点需要基于真实商品信息表达，不使用绝对化承诺。\n"
    )


def packageGroupName(group: str) -> str:
    return {
        "remix": "图文/视频包",
        "jianying": "剪映包",
        "affiliate-jianying": "带货剪映包",
        "xiaohongshu-note": "小红书图文包",
        "douyin-note": "抖音图文包",
    }.get(group, group or "未知")


def read_remix_package_file(root: Path, relative_path: str) -> Dict[str, Any]:
    file_path = resolve_remix_package_file(root, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise ValueError("文件不存在")
    editable = file_path.suffix.lower() in REMIX_EDITABLE_SUFFIXES
    if not editable:
        raise ValueError("该文件不支持在线编辑")
    return {
        "ok": True,
        "path": file_path.relative_to((root / "remix_packages").resolve()).as_posix(),
        "name": file_path.name,
        "editable": editable,
        "content": file_path.read_text(encoding="utf-8"),
    }


def save_remix_package_file(root: Path, relative_path: str, content: str) -> Dict[str, Any]:
    file_path = resolve_remix_package_file(root, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise ValueError("文件不存在")
    if file_path.suffix.lower() not in REMIX_EDITABLE_SUFFIXES:
        raise ValueError("该文件不支持在线编辑")
    file_path.write_text(str(content or ""), encoding="utf-8")
    return {"ok": True, "path": file_path.relative_to((root / "remix_packages").resolve()).as_posix(), "size": file_path.stat().st_size}


def resolve_remix_package_file(root: Path, relative_path: str) -> Path:
    packages_root = (root / "remix_packages").resolve()
    file_path = (packages_root / str(relative_path or "")).resolve()
    if not str(file_path).startswith(str(packages_root)) or file_path == packages_root:
        raise ValueError("非法文件路径")
    return file_path


def performance_summary(root: Path) -> Dict[str, Any]:
    rows = []
    for project in list_projects(root):
        for row in project.get("performance", []):
            normalized = normalize_performance_row(row)
            normalized["project_id"] = project["id"]
            rows.append(normalized)

    platform_totals: Dict[str, Dict[str, Any]] = {}
    project_scores: Dict[str, float] = {}
    total_views = 0
    for row in rows:
        platform = row["platform"] or "unknown"
        total_views += row["views"]
        bucket = platform_totals.setdefault(
            platform,
            {
                "platform": platform,
                "views": 0,
                "likes": 0,
                "comments": 0,
                "favorites": 0,
                "shares": 0,
                "followers_delta": 0,
                "score": 0.0,
            },
        )
        for key in ("views", "likes", "comments", "favorites", "shares", "followers_delta"):
            bucket[key] += row[key]
        row_score = performance_insights([row])["rows"][0]["score"] if row["platform"] else 0
        bucket["score"] += row_score
        project_scores[row["project_id"]] = project_scores.get(row["project_id"], 0.0) + row_score

    for bucket in platform_totals.values():
        views = bucket["views"]
        interactions = bucket["likes"] + bucket["comments"] + bucket["favorites"] + bucket["shares"]
        bucket["engagement_rate"] = round(_rate(interactions, views), 4)
        bucket["favorite_rate"] = round(_rate(bucket["favorites"], views), 4)
        bucket["follower_rate"] = round(_rate(bucket["followers_delta"], views), 4)
        bucket["score"] = round(bucket["score"], 4)

    best_platform = max(platform_totals.values(), key=lambda item: item["score"], default={}).get("platform", "")
    best_project = max(project_scores.items(), key=lambda item: item[1], default=("", 0))[0]
    return {
        "ok": True,
        "total_projects": len({row["project_id"] for row in rows}),
        "total_views": total_views,
        "best_platform": best_platform,
        "best_project": best_project,
        "platforms": platform_totals,
        "suggestions": performance_summary_suggestions(platform_totals, best_platform),
    }


def performance_summary_suggestions(platforms: Dict[str, Dict[str, Any]], best_platform: str) -> List[str]:
    if not platforms:
        return ["还没有全局复盘数据。发布后先回填 performance.csv，再判断平台方向。"]
    suggestions = []
    if best_platform:
        suggestions.append(f"当前全局表现最好的平台是 {_platform_name(best_platform)}，优先围绕该平台做系列化选题。")
    if all(item["favorite_rate"] < 0.02 for item in platforms.values()):
        suggestions.append("全平台收藏率偏低，下一批内容优先做可收藏的清单、步骤和结论卡。")
    if all(item["follower_rate"] < 0.005 for item in platforms.values()):
        suggestions.append("全平台涨粉效率偏低，结尾需要更强关注理由、系列预告或主页承接。")
    return suggestions or ["全局数据健康，继续保留表现最好平台的标题、封面和节奏模板。"]


def project_updated_at(project_dir: Path) -> float:
    latest = project_dir.stat().st_mtime
    for path in project_dir.rglob("*"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def project_summary(root: Path, project_dir: Path) -> Dict[str, Any]:
    manifest = project_dir / "episode.yaml"
    script = project_dir / "script.txt"
    audio = project_voice_audio(project_dir)
    subtitles = project_dir / "exports" / "subtitles.srt"
    video = project_dir / "exports" / "preview.mp4"
    image_dir = project_dir / "assets" / "images"
    bgm_dir = project_dir / "assets" / "bgm"
    image_count = _file_count(image_dir)
    bgm_count = _file_count(bgm_dir)
    performance = read_project_performance(root, project_dir.name).get("performance", [])
    title_experiments = read_title_experiments(root, project_dir.name).get("title_experiments", [])
    hook = read_hook_analysis(root, project_dir.name).get("hook_analysis", {})
    monetization = read_monetization_plan(root, project_dir.name).get("monetization_plan", {})
    series = read_series_plan(root, project_dir.name).get("series_plan", {})
    schedule = read_publish_schedule(root, project_dir.name).get("publish_schedule", {})
    return {
        "id": project_dir.name,
        "manifest": manifest.read_text(encoding="utf-8") if manifest.exists() else "",
        "has_script": script.exists(),
        "has_audio": audio.exists(),
        "has_subtitles": subtitles.exists(),
        "has_video": video.exists(),
        "can_preview": audio.exists() and subtitles.exists(),
        "image_count": image_count,
        "bgm_count": bgm_count,
        "platform_packages": list_platform_packages(project_dir),
        "performance": performance,
        "performance_insights": performance_insights(performance),
        "title_experiments": title_experiments,
        "hook_analysis": hook,
        "monetization_plan": monetization,
        "series_plan": series,
        "publish_schedule": schedule,
        "script": _relative(root, script) if script.exists() else "",
        "audio": _relative(root, audio) if audio.exists() else "",
        "subtitles": _relative(root, subtitles) if subtitles.exists() else "",
        "video": _relative(root, video) if video.exists() else "",
    }


def list_platform_packages(project_dir: Path) -> List[Dict[str, Any]]:
    packages_dir = project_dir / "exports" / "platforms"
    if not packages_dir.exists():
        return []
    packages = []
    for metadata_path in sorted(packages_dir.glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = metadata_path.parent.name
        video = metadata_path.parent / "video.mp4"
        cover = metadata_path.parent / "cover.png"
        package = metadata_path.parent / "publish-package.zip"
        packages.append(
            {
                "key": key,
                "name": metadata.get("platform", {}).get("name", key),
                "title": metadata.get("title", ""),
                "score": metadata.get("traffic_score"),
                "aspect_ratio": metadata.get("platform", {}).get("aspect_ratio", ""),
                "video": media_url(project_dir.name, "exports", "platforms", key, "video.mp4") if video.exists() else "",
                "cover": media_url(project_dir.name, "exports", "platforms", key, "cover.png") if cover.exists() else "",
                "package": media_url(project_dir.name, "exports", "platforms", key, "publish-package.zip") if package.exists() else "",
                "technical_checklist": metadata.get("technical_checklist", []),
                "traffic_checklist": metadata.get("traffic_checklist", []),
                "risk_checks": metadata.get("risk_checks", []),
                "improvement_suggestions": metadata.get("improvement_suggestions", []),
                "title_variants": metadata.get("title_variants", []),
                "hashtags": metadata.get("hashtags", []),
                "description": metadata.get("description", ""),
                "comment_prompt": metadata.get("comment_prompt", ""),
                "conversion_cta": metadata.get("conversion_cta", ""),
            }
        )
    return packages


def read_project_performance(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    performance = project_dir / "exports" / "performance.csv"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "performance": []}
    if not performance.exists():
        return {"ok": True, "project_id": project_id, "performance": []}
    rows = []
    with performance.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for raw_row in reader:
            rows.append(normalize_performance_row(raw_row))
    return {"ok": True, "project_id": project_id, "performance": rows}


def read_title_experiments(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    path = project_dir / "exports" / "title-experiments.csv"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "title_experiments": []}
    if not path.exists():
        rows = title_experiments_from_platform_metadata(project_dir)
        if rows:
            save_title_experiments(root, project_id, rows)
            return {"ok": True, "project_id": project_id, "title_experiments": rows}
        return {"ok": True, "project_id": project_id, "title_experiments": []}
    rows = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for raw_row in reader:
            rows.append(normalize_title_experiment_row(raw_row))
    return {"ok": True, "project_id": project_id, "title_experiments": rows}


def read_hook_analysis(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    path = project_dir / "exports" / "hook-analysis.json"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "hook_analysis": {}}
    if path.exists():
        try:
            return {"ok": True, "project_id": project_id, "hook_analysis": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "project_id": project_id, "hook_analysis": {}}
    script = project_dir / "script.txt"
    if not script.exists():
        return {"ok": True, "project_id": project_id, "hook_analysis": {}}
    platforms = [preset.key for preset in selected_platform_presets(project_dir)]
    analysis = hook_analysis(script.read_text(encoding="utf-8"), 0, platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "project_id": project_id, "hook_analysis": analysis}


def read_monetization_plan(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    path = project_dir / "exports" / "monetization-plan.json"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "monetization_plan": {}}
    if path.exists():
        try:
            return {"ok": True, "project_id": project_id, "monetization_plan": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "project_id": project_id, "monetization_plan": {}}
    script = project_dir / "script.txt"
    if not script.exists():
        return {"ok": True, "project_id": project_id, "monetization_plan": {}}
    platforms = [preset.key for preset in selected_platform_presets(project_dir)]
    plan = monetization_plan(script.read_text(encoding="utf-8"), 0, platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "project_id": project_id, "monetization_plan": plan}


def read_series_plan(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    path = project_dir / "exports" / "series-plan.json"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "series_plan": {}}
    if path.exists():
        try:
            return {"ok": True, "project_id": project_id, "series_plan": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "project_id": project_id, "series_plan": {}}
    script = project_dir / "script.txt"
    if not script.exists():
        return {"ok": True, "project_id": project_id, "series_plan": {}}
    platforms = [preset.key for preset in selected_platform_presets(project_dir)]
    plan = series_plan(script.read_text(encoding="utf-8"), 0, platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "project_id": project_id, "series_plan": plan}


def read_publish_schedule(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    path = project_dir / "exports" / "publish-schedule.json"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}", "publish_schedule": {}}
    if path.exists():
        try:
            return {"ok": True, "project_id": project_id, "publish_schedule": json.loads(path.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "project_id": project_id, "publish_schedule": {}}
    script = project_dir / "script.txt"
    if not script.exists():
        return {"ok": True, "project_id": project_id, "publish_schedule": {}}
    platforms = [preset.key for preset in selected_platform_presets(project_dir)]
    schedule = publish_schedule(script.read_text(encoding="utf-8"), 0, platforms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "project_id": project_id, "publish_schedule": schedule}


def title_experiments_from_platform_metadata(project_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for metadata_path in sorted((project_dir / "exports" / "platforms").glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        platform = metadata_path.parent.name
        platform_name = metadata.get("platform", {}).get("name") or _platform_name(platform)
        for index, title in enumerate(metadata.get("title_variants", []), start=1):
            rows.append(
                normalize_title_experiment_row(
                    {
                        "platform": platform,
                        "platform_name": platform_name,
                        "variant_index": index,
                        "title": title,
                        "hypothesis": metadata_title_hypothesis(platform, index),
                        "selected": "yes" if index == 1 else "",
                    }
                )
            )
    return rows


def metadata_title_hypothesis(platform: str, index: int) -> str:
    defaults = {
        "bilibili": ["问题钩子", "反常识表达", "共情表达", "机制解释", "讲透型表达"],
        "xiaohongshu": ["共情收藏", "真实感表达", "人群代入", "原因解释", "搜索转化"],
        "douyin": ["首屏停留", "纠偏互动", "反转完播", "短利益点", "转粉提醒"],
    }
    values = defaults.get(platform, ["点击测试"])
    return values[min(max(index - 1, 0), len(values) - 1)]


def save_title_experiments(root: Path, project_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}"}
    path = project_dir / "exports" / "title-experiments.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_title_experiment_row(row) for row in rows]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TITLE_EXPERIMENT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in normalized:
        writer.writerow({column: row.get(column, "") for column in TITLE_EXPERIMENT_COLUMNS})
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return {
        "ok": True,
        "project_id": project_id,
        "title_experiments": normalized,
        "path": str(path),
    }


def normalize_title_experiment_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {column: row.get(column, "") for column in TITLE_EXPERIMENT_COLUMNS}
    normalized["platform"] = str(normalized.get("platform") or "").strip()
    normalized["platform_name"] = str(normalized.get("platform_name") or _platform_name(normalized["platform"])).strip()
    normalized["title"] = str(normalized.get("title") or "").strip()
    normalized["hypothesis"] = str(normalized.get("hypothesis") or "").strip()
    normalized["selected"] = "yes" if str(normalized.get("selected") or "").strip().lower() in {"yes", "true", "1", "是"} else ""
    normalized["publish_url"] = str(normalized.get("publish_url") or "").strip()
    normalized["click_rate"] = _rate_value(normalized.get("click_rate"))
    normalized["notes"] = str(normalized.get("notes") or "").strip()
    for column in TITLE_EXPERIMENT_NUMBER_COLUMNS:
        normalized[column] = _int_value(normalized.get(column))
    return normalized


def save_project_performance(root: Path, project_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}"}
    performance = project_dir / "exports" / "performance.csv"
    performance.parent.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_performance_row(row) for row in rows]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PERFORMANCE_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in normalized:
        writer.writerow({column: row.get(column, "") for column in PERFORMANCE_COLUMNS})
    performance.write_text(buffer.getvalue(), encoding="utf-8")
    return {
        "ok": True,
        "project_id": project_id,
        "performance": normalized,
        "performance_insights": performance_insights(normalized),
        "path": str(performance),
    }


def normalize_performance_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {column: row.get(column, "") for column in PERFORMANCE_COLUMNS}
    normalized["platform"] = str(normalized.get("platform") or "").strip()
    normalized["status"] = str(normalized.get("status") or "planned").strip() or "planned"
    normalized["publish_url"] = str(normalized.get("publish_url") or "").strip()
    normalized["conversion_notes"] = str(normalized.get("conversion_notes") or "").strip()
    normalized["review_notes"] = str(normalized.get("review_notes") or "").strip()
    for column in PERFORMANCE_NUMBER_COLUMNS:
        normalized[column] = _int_value(normalized.get(column))
    return normalized


def _int_value(value: Any) -> int:
    try:
        return max(0, int(str(value or 0).strip()))
    except ValueError:
        return 0


def _rate_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        number = max(0.0, float(text))
    except ValueError:
        return ""
    return str(round(number, 4)).rstrip("0").rstrip(".")


def performance_insights(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = []
    for row in rows:
        normalized = normalize_performance_row(row)
        views = normalized["views"]
        interactions = (
            normalized["likes"]
            + normalized["comments"]
            + normalized["favorites"]
            + normalized["shares"]
        )
        engagement_rate = _rate(interactions, views)
        favorite_rate = _rate(normalized["favorites"], views)
        follower_rate = _rate(normalized["followers_delta"], views)
        score = round(engagement_rate * 55 + favorite_rate * 30 + follower_rate * 100 + min(views / 10000, 1) * 15, 4)
        scored.append(
            {
                "platform": normalized["platform"],
                "views": views,
                "engagement_rate": round(engagement_rate, 4),
                "favorite_rate": round(favorite_rate, 4),
                "follower_rate": round(follower_rate, 4),
                "score": score,
            }
        )
    best = max(scored, key=lambda item: item["score"], default=None)
    return {
        "best_platform": best["platform"] if best else "",
        "rows": scored,
        "suggestions": performance_suggestions(scored, best),
    }


def performance_suggestions(scored: List[Dict[str, Any]], best: Dict[str, Any] | None) -> List[str]:
    if not scored:
        return ["发布后回填播放、点赞、收藏、评论和涨粉，才能反推平台策略。"]
    suggestions = []
    if best and best["platform"]:
        suggestions.append(f"{_platform_name(best['platform'])} 当前综合表现最好，下一条优先复用它的标题和封面方向。")
    if all(row["views"] < 1000 for row in scored):
        suggestions.append("整体播放偏低，优先测试更强封面钩子和前 3 秒冲突表达。")
    if all(row["favorite_rate"] < 0.02 for row in scored):
        suggestions.append("收藏率偏低，建议把内容改成更可保存的清单、步骤或结论卡。")
    if all(row["follower_rate"] < 0.005 for row in scored):
        suggestions.append("涨粉效率偏低，结尾需要更明确的系列预告或主页转化理由。")
    return suggestions or ["当前数据健康，继续做同主题系列并保留标题/封面对照。"]


def _rate(value: int, denominator: int) -> float:
    return value / denominator if denominator > 0 else 0.0


def _platform_name(platform: str) -> str:
    return {"bilibili": "哔哩哔哩", "douyin": "抖音", "xiaohongshu": "小红书"}.get(platform, platform)


def package_platform_publish(root: Path, project_id: str, platform: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    platform_dir = project_dir / "exports" / "platforms" / safe_path_part(platform)
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}"}
    if not platform_dir.exists():
        return {"ok": False, "error": f"平台发布包不存在: {platform}"}
    ensure_platform_video(root, project_id, platform)

    candidates = [
        platform_dir / "video.mp4",
        platform_dir / "cover.png",
        platform_dir / "cover.svg",
        platform_dir / "publish.md",
        platform_dir / "metadata.json",
        project_dir / "script.txt",
        project_dir / "episode.yaml",
        project_dir / "assets" / "licenses.md",
        project_dir / "exports" / "performance.csv",
        project_dir / "exports" / "title-experiments.csv",
        project_dir / "exports" / "hook-analysis.json",
        project_dir / "exports" / "monetization-plan.json",
        project_dir / "exports" / "series-plan.json",
        project_dir / "exports" / "publish-schedule.json",
        project_dir / "exports" / "subtitles.srt",
        project_dir / "exports" / "subtitles.ass",
    ]
    candidates.extend(sorted(platform_dir.glob("short-*.mp4")))
    package = platform_dir / "publish-package.zip"
    files = []
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            archive_name = path.name if path.parent == platform_dir else str(path.relative_to(project_dir))
            archive.write(path, archive_name)
            files.append(archive_name)
    if not files:
        return {"ok": False, "error": "没有可打包的发布文件"}
    return {
        "ok": True,
        "project_id": project_id,
        "platform": platform,
        "package": str(package),
        "package_url": media_url(project_id, "exports", "platforms", platform, package.name),
        "files": files,
    }


def ensure_platform_video(root: Path, project_id: str, platform: str) -> None:
    project_dir = root / "projects" / project_id
    preset = PLATFORM_PRESETS.get(platform)
    if not preset:
        return
    output = project_dir / "exports" / "platforms" / platform / "video.mp4"
    if output.exists():
        return
    ffmpeg = find_ffmpeg_with_subtitles()
    audio = ensure_browser_audio(project_voice_audio(project_dir))
    if not ffmpeg or not audio or not audio.exists():
        return
    image = first_project_image(project_dir) or default_cover_image(root)
    bgm = first_project_bgm(project_dir)
    srt = project_dir / "exports" / "subtitles.srt"
    ass = project_dir / "exports" / "subtitles.ass"
    if srt.exists():
        write_ass_subtitles(srt, ass)
    visual_source, image_sequence = prepare_visual_source(project_dir, image, audio, read_project_target_duration(project_dir))
    output.parent.mkdir(parents=True, exist_ok=True)
    command = export_video_command(
        ffmpeg,
        project_dir,
        visual_source,
        audio,
        ass if ass.exists() else None,
        output,
        target_size=preset.target_size,
        bgm=bgm,
        target_duration_seconds=read_project_target_duration(project_dir),
        image_sequence=image_sequence,
    )
    result = run_ffmpeg(command, project_dir)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"{preset.name} 平台视频生成失败")


def list_voices() -> List[str]:
    return [CAPCUT_CALM_MALE_LABEL, REFERENCE_VOICE_LABEL]


def resolve_voice_preset(voice: Any) -> str:
    text = str(voice or "").strip()
    if text in ("", CAPCUT_CALM_MALE_LABEL):
        return CAPCUT_CALM_MALE_ENGINE
    if text == REFERENCE_VOICE_LABEL:
        return REFERENCE_VOICE_ENGINE
    return CAPCUT_CALM_MALE_ENGINE


def generate_voice(root: Path, project_id: str) -> Dict[str, Any]:
    script = root / "projects" / project_id / "voice" / "generate_voice.sh"
    if not script.exists():
        return {"ok": False, "error": f"未找到口播脚本: {script}"}
    result = subprocess.run([str(script)], text=True, capture_output=True, check=False, cwd=root)
    project_dir = root / "projects" / project_id
    audio = project_voice_audio(project_dir)
    browser_audio = ensure_browser_audio(audio)
    duration = audio_duration_seconds(audio) if audio.exists() else None
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "audio": str(audio),
        "browser_audio": str(browser_audio) if browser_audio else "",
        "duration": duration,
    }


def align_subtitles(root: Path, project_id: str) -> Dict[str, Any]:
    code = align_project(project_id=project_id, audio=None, chars_per_second=4.8)
    srt = root / "projects" / project_id / "exports" / "subtitles.srt"
    return {
        "ok": code == 0,
        "srt": str(srt),
        "preview": srt.read_text(encoding="utf-8")[:2000] if srt.exists() else "",
    }


def preview_project(root: Path, project_id: str) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    audio = ensure_browser_audio(project_voice_audio(project_dir))
    srt = project_dir / "exports" / "subtitles.srt"
    video = project_dir / "exports" / "preview.mp4"
    image_dir = project_dir / "assets" / "images"
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}"}
    if not audio or not audio.exists():
        return {"ok": False, "error": "还没有口播音频，请先点击生成口播"}
    if not srt.exists():
        return {"ok": False, "error": "还没有字幕，请先生成项目"}
    images = []
    if image_dir.exists():
        for image in sorted(path for path in image_dir.iterdir() if path.is_file()):
            images.append(media_url(project_id, "assets", "images", image.name))
    return {
        "ok": True,
        "project_id": project_id,
        "audio_url": media_url(project_id, "voice", audio.name),
        "video_url": media_url(project_id, "exports", video.name) if video.exists() else "",
        "subtitles": parse_srt(srt.read_text(encoding="utf-8")),
        "images": images,
    }


def export_video(root: Path, project_id: str, target_duration_seconds: float | None = None, include_platforms: bool = False) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    if not project_dir.exists():
        return {"ok": False, "error": f"项目不存在: {project_id}"}
    if not start_video_job(project_id):
        return {"ok": False, "error": "这个项目的视频正在生成中，请等待当前任务结束。", "busy": True}
    try:
        return _export_video(root, project_id, target_duration_seconds=target_duration_seconds, include_platforms=include_platforms)
    finally:
        finish_video_job(project_id)


def _export_video(root: Path, project_id: str, target_duration_seconds: float | None = None, include_platforms: bool = False) -> Dict[str, Any]:
    project_dir = root / "projects" / project_id
    ffmpeg = find_ffmpeg_with_subtitles()
    if not ffmpeg:
        return {
            "ok": False,
            "error": "缺少支持 subtitles/libass 滤镜的 FFmpeg，无法生成 ASS 高级硬字幕 MP4。请安装: brew install ffmpeg-full",
        }
    audio = ensure_browser_audio(project_voice_audio(project_dir))
    if not audio or not audio.exists():
        return {"ok": False, "error": "还没有口播音频，请先点击生成口播"}
    image = first_project_image(project_dir) or default_cover_image(root)
    bgm = first_project_bgm(project_dir)
    srt = project_dir / "exports" / "subtitles.srt"
    ass = project_dir / "exports" / "subtitles.ass"
    if srt.exists():
        write_ass_subtitles(srt, ass)
    output = project_dir / "exports" / "preview.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    requested_duration = target_duration_seconds or audio_duration_seconds(audio) or read_project_target_duration(project_dir)
    visual_source, image_sequence = prepare_visual_source(project_dir, image, audio, requested_duration)
    command = export_video_command(
        ffmpeg,
        project_dir,
        visual_source,
        audio,
        ass if ass.exists() else None,
        output,
        bgm=bgm,
        target_duration_seconds=requested_duration,
        image_sequence=image_sequence,
    )
    result = run_ffmpeg(command, project_dir)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr or result.stdout or "ffmpeg 生成 MP4 失败"}
    platform_videos = {}
    short_clips = {}
    cover_images = {}
    if include_platforms:
        platform_videos = export_platform_videos(
            ffmpeg,
            project_dir,
            visual_source,
            audio,
            ass if ass.exists() else None,
            bgm,
            target_duration_seconds=requested_duration,
            image_sequence=image_sequence,
        )
        short_clips = export_short_clips(ffmpeg, project_dir)
        cover_images = export_cover_pngs(ffmpeg, project_dir)
    return {
        "ok": True,
        "project_id": project_id,
        "video": str(output),
        "video_url": media_url(project_id, "exports", output.name),
        "target_duration_seconds": requested_duration or "",
        "platform_videos": platform_videos,
        "short_clips": short_clips,
        "cover_images": cover_images,
    }


def start_video_job(project_id: str) -> bool:
    with VIDEO_JOBS_LOCK:
        if project_id in VIDEO_JOBS:
            return False
        VIDEO_JOBS.add(project_id)
        return True


def finish_video_job(project_id: str) -> None:
    with VIDEO_JOBS_LOCK:
        VIDEO_JOBS.discard(project_id)


def export_platform_videos(
    ffmpeg: str,
    project_dir: Path,
    image: Path,
    audio: Path,
    ass: Path | None,
    bgm: Path | None,
    target_duration_seconds: float | None = None,
    image_sequence: bool = False,
) -> Dict[str, str]:
    videos = {}
    for preset in selected_platform_presets(project_dir):
        key = preset.key
        output = project_dir / "exports" / "platforms" / key / "video.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        command = export_video_command(
            ffmpeg,
            project_dir,
            image,
            audio,
            ass,
            output,
            target_size=preset.target_size,
            bgm=bgm,
            target_duration_seconds=target_duration_seconds,
            image_sequence=image_sequence,
        )
        result = run_ffmpeg(command, project_dir)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or f"{preset.name} 平台视频生成失败")
        videos[key] = str(output)
    return videos


def selected_platform_presets(project_dir: Path) -> List[Any]:
    packages_dir = project_dir / "exports" / "platforms"
    if not packages_dir.exists():
        return list(PLATFORM_PRESETS.values())
    selected = []
    for key, preset in PLATFORM_PRESETS.items():
        if (packages_dir / key / "metadata.json").exists():
            selected.append(preset)
    return selected or list(PLATFORM_PRESETS.values())


def export_short_clips(ffmpeg: str, project_dir: Path) -> Dict[str, List[str]]:
    clips = {}
    for key, seconds in {"douyin": 60, "xiaohongshu": 90}.items():
        source = project_dir / "exports" / "platforms" / key / "video.mp4"
        if not source.exists():
            continue
        output_pattern = project_dir / "exports" / "platforms" / key / "short-%02d.mp4"
        command = export_short_clips_command(ffmpeg, project_dir, source, output_pattern, seconds)
        result = run_ffmpeg(command, project_dir)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or f"{key} 短视频切片生成失败")
        clips[key] = [str(path) for path in sorted(output_pattern.parent.glob("short-*.mp4"))]
    return clips


def export_short_clips_command(
    ffmpeg: str,
    project_dir: Path,
    source: Path,
    output_pattern: Path,
    seconds: int,
) -> List[str]:
    return [
        ffmpeg,
        "-y",
        "-i",
        _ffmpeg_path(project_dir, source),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{seconds})",
        "-f",
        "segment",
        "-segment_time",
        str(seconds),
        "-reset_timestamps",
        "1",
        _relative(project_dir, output_pattern),
    ]


def export_cover_pngs(ffmpeg: str, project_dir: Path) -> Dict[str, str]:
    covers = {}
    for svg in sorted((project_dir / "exports" / "platforms").glob("*/cover.svg")):
        output = svg.with_suffix(".png")
        if convert_svg_cover_to_png(svg, output, ffmpeg):
            covers[svg.parent.name] = str(output)
    return covers


def convert_svg_cover_to_png(svg: Path, output: Path, ffmpeg: str) -> bool:
    if shutil.which("qlmanage"):
        result = subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", str(output.parent), str(svg)],
            text=True,
            capture_output=True,
            check=False,
        )
        ql_output = output.parent / f"{svg.name}.png"
        if result.returncode == 0 and ql_output.exists():
            ql_output.replace(output)
            return True
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(svg), str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and output.exists()


def export_video_command(
    ffmpeg: str,
    project_dir: Path,
    image: Path,
    audio: Path,
    ass: Path | None,
    output: Path,
    target_size: str | None = None,
    bgm: Path | None = None,
    target_duration_seconds: float | None = None,
    threads: int = DEFAULT_FFMPEG_THREADS,
    image_sequence: bool = False,
) -> List[str]:
    command = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        str(max(1, threads)),
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
    ]
    if image_sequence:
        command.extend([
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            _ffmpeg_path(project_dir, image),
        ])
    else:
        command.extend([
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        _ffmpeg_path(project_dir, image),
        ])
    command.extend([
        "-i",
        _ffmpeg_path(project_dir, audio),
    ])
    if bgm:
        command.extend(["-stream_loop", "-1", "-i", _ffmpeg_path(project_dir, bgm)])
    filters = [video_scale_filter(target_size, motion=True)]
    if ass:
        filters.append(f"subtitles=filename={escape_ffmpeg_filter_path(Path(_relative(project_dir, ass)))}")
    command.extend(["-vf", ",".join(filters)])
    if bgm:
        command.extend(
            [
                "-filter_complex",
                "[1:a]volume=1.0[a0];[2:a]volume=0.18[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                "-map",
                "0:v",
                "-map",
                "[aout]",
            ]
        )
    if target_duration_seconds:
        command.extend(["-t", str(round(target_duration_seconds, 3))])
    command.extend([
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        TARGET_VIDEO_BITRATE,
        "-maxrate",
        "9000k",
        "-bufsize",
        "12000k",
        "-c:a",
        "aac",
        "-ar",
        TARGET_AUDIO_RATE,
        "-ac",
        "2",
        "-b:a",
        TARGET_AUDIO_BITRATE,
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-movflags",
        "+faststart",
        _relative(project_dir, output),
    ])
    if not target_duration_seconds:
        command.insert(-3, "-shortest")
    return command


def video_scale_filter(target_size: str | None = None, motion: bool = False) -> str:
    width, height = (1280, 720)
    if not target_size:
        pass
    else:
        width_text, height_text = target_size.split("x", 1)
        width, height = int(width_text), int(height_text)
    if motion:
        return (
            f"fps=30,scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "zoompan=z='min(zoom+0.0008,1.08)':d=1:"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps=30"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def ffmpeg_supports_subtitles_filter(ffmpeg: str) -> bool:
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    return any(" subtitles " in line or line.strip().startswith("subtitles ") for line in result.stdout.splitlines())


def run_ffmpeg(command: List[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, cwd=cwd)


def find_ffmpeg_with_subtitles() -> str | None:
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
        shutil.which("ffmpeg-full"),
        shutil.which("ffmpeg"),
    ]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if ffmpeg_supports_subtitles_filter(candidate):
            return candidate
    return None


def _target_duration_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        raise ValueError("目标视频时长必须是数字秒数")
    if seconds <= 0:
        return None
    return min(seconds, MAX_TARGET_DURATION_SECONDS)


def read_project_target_duration(project_dir: Path) -> float | None:
    manifest = project_dir / "episode.yaml"
    if not manifest.exists():
        return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("estimated_duration_seconds:"):
            return _target_duration_seconds(line.split(":", 1)[1])
    return None


def write_ass_subtitles(srt: Path, ass: Path) -> None:
    entries = parse_srt(srt.read_text(encoding="utf-8"))
    dialogues = []
    for entry in entries:
        text = ass_escape_text(str(entry["text"]))
        dialogues.append(
            f"Dialogue: 0,{ass_time(float(entry['start']))},{ass_time(float(entry['end']))},Default,,0,0,0,,{text}"
        )
    ass.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial Unicode MS,64,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,"
        "1,0,0,0,100,100,0,0,1,5,1,2,120,120,96,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(dialogues)
        + ("\n" if dialogues else ""),
        encoding="utf-8",
    )


def ass_time(seconds: float) -> str:
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def ass_escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def escape_ffmpeg_filter_path(path: Path) -> str:
    text = str(path)
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def prepare_visual_source(
    project_dir: Path,
    fallback_image: Path,
    audio: Path,
    target_duration_seconds: float | None = None,
) -> tuple[Path, bool]:
    images = all_project_images(project_dir)
    if len(images) <= 1:
        return fallback_image, False

    duration = target_duration_seconds or audio_duration_seconds(audio) or len(images) * 5
    per_image = max(2.5, duration / len(images))
    concat = project_dir / "exports" / "slideshow.ffconcat"
    concat.parent.mkdir(parents=True, exist_ok=True)
    lines = ["ffconcat version 1.0"]
    for image in images:
        lines.append(f"file {_ffconcat_quote(image)}")
        lines.append(f"duration {per_image:.3f}")
    lines.append(f"file {_ffconcat_quote(images[-1])}")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat, True


def all_project_images(project_dir: Path) -> List[Path]:
    image_dir = project_dir / "assets" / "images"
    if not image_dir.exists():
        return []
    return [
        image
        for image in sorted(path for path in image_dir.iterdir() if path.is_file())
        if image.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]


def _ffconcat_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def project_voice_audio(project_dir: Path) -> Path:
    voice_dir = project_dir / "voice"
    for name in ("voice.mp3", "voice.wav", "voice.aiff", "voice.aif"):
        candidate = voice_dir / name
        if candidate.exists():
            return candidate
    return voice_dir / "voice.aiff"


def first_project_image(project_dir: Path) -> Path | None:
    image_dir = project_dir / "assets" / "images"
    if not image_dir.exists():
        return None
    for image in sorted(path for path in image_dir.iterdir() if path.is_file()):
        if image.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            return image
    return None


def first_project_bgm(project_dir: Path) -> Path | None:
    bgm_dir = project_dir / "assets" / "bgm"
    if not bgm_dir.exists():
        return None
    for bgm in sorted(path for path in bgm_dir.iterdir() if path.is_file()):
        if bgm.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".aiff", ".aif"}:
            return bgm
    return None


def default_cover_image(root: Path) -> Path:
    cover = root / "web" / "default-cover.ppm"
    if not cover.exists() or _ppm_has_odd_dimensions(cover):
        width, height = 1280, 720
        cover.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + bytes([20, 25, 34]) * width * height)
    return cover


def _ppm_has_odd_dimensions(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            magic = file.readline().strip()
            if magic not in {b"P3", b"P6"}:
                return False
            line = file.readline().strip()
            while line.startswith(b"#"):
                line = file.readline().strip()
            width, height = [int(part) for part in line.split()[:2]]
            return width % 2 != 0 or height % 2 != 0
    except (OSError, ValueError):
        return True


def ensure_browser_audio(audio_path: Path) -> Path | None:
    if audio_path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}:
        return audio_path if audio_path.exists() else None
    wav_path = audio_path.with_suffix(".wav")
    if wav_path.exists():
        return wav_path
    if not audio_path.exists():
        return None
    if shutil.which("afconvert"):
        result = subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16", str(audio_path), str(wav_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and wav_path.exists():
            return wav_path
    return audio_path


def media_url(*parts: str) -> str:
    return "/media/" + "/".join(quote(part, safe="") for part in parts)


def parse_srt(srt_text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for block in re_split_srt_blocks(srt_text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split("-->", 1)]
        entries.append(
            {
                "index": int(lines[0]) if lines[0].isdigit() else len(entries) + 1,
                "start": srt_time_to_seconds(start),
                "end": srt_time_to_seconds(end),
                "text": "\n".join(lines[2:]),
            }
        )
    return entries


def re_split_srt_blocks(srt_text: str) -> List[str]:
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return [block for block in normalized.split("\n\n") if block.strip()]


def srt_time_to_seconds(value: str) -> float:
    hours_text, minutes_text, rest = value.split(":")
    seconds_text, millis_text = rest.split(",")
    return (
        int(hours_text) * 3600
        + int(minutes_text) * 60
        + int(seconds_text)
        + int(millis_text) / 1000
    )


def run_server(host: str = "127.0.0.1", port: int = 8765, root: Path = ROOT) -> None:
    handler = _make_handler(root)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"本地视频工作流前端已启动: http://{host}:{port}")
    server.serve_forever()


def _make_handler(root: Path):
    class WorkflowHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                self._send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path == "/remix.html":
                self._send_file(WEB_DIR / "remix.html", "text/html; charset=utf-8")
                return
            if path == "/app.css":
                self._send_file(WEB_DIR / "app.css", "text/css; charset=utf-8")
                return
            if path == "/app.js":
                self._send_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
                return
            if path == "/remix.js":
                self._send_file(WEB_DIR / "remix.js", "application/javascript; charset=utf-8")
                return
            if path == "/api/voices":
                self._json({"ok": True, "voices": list_voices()})
                return
            if path == "/api/bgm-sources":
                self._json({"ok": True, "sources": bgm_source_catalog()})
                return
            if path == "/api/projects":
                self._json({"ok": True, "projects": list_projects(root)})
                return
            if path == "/api/analytics":
                self._json(performance_summary(root))
                return
            if path == "/api/remix/models":
                self._json(list_llmstudio_models())
                return
            if path == "/api/remix/packages":
                self._json(list_remix_packages(root))
                return
            if path == "/api/remix/content/jianying-job":
                job_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(jianying_automation_job_status(job_id))
                return
            if path == "/api/remix/file":
                relative_path = parse_qs(parsed.query).get("path", [""])[0]
                self._json(read_remix_package_file(root, relative_path))
                return
            if path == "/api/preview":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(preview_project(root, project_id))
                return
            if path == "/api/performance":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_project_performance(root, project_id))
                return
            if path == "/api/title-experiments":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_title_experiments(root, project_id))
                return
            if path == "/api/hook-analysis":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_hook_analysis(root, project_id))
                return
            if path == "/api/monetization-plan":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_monetization_plan(root, project_id))
                return
            if path == "/api/series-plan":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_series_plan(root, project_id))
                return
            if path == "/api/publish-schedule":
                project_id = parse_qs(parsed.query).get("project", [""])[0]
                self._json(read_publish_schedule(root, project_id))
                return
            if path.startswith("/media/"):
                self._send_project_media(root, path)
                return
            if path.startswith("/generated/"):
                self._send_generated_file(root, path)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/upload":
                    kind = parse_qs(parsed.query).get("kind", ["files"])[0]
                    self._json(save_uploaded_files(root, self.headers.get("Content-Type", ""), self._read_body(), kind))
                    return
                payload = self._read_json()
                if path == "/api/bgm-download":
                    self._json(download_bgm_from_url(root, payload))
                    return
                if path == "/api/project":
                    self._json(create_project_from_payload(root, payload))
                    return
                if path == "/api/remix/analyze":
                    self._json(analyze_remix_link(payload))
                    return
                if path == "/api/remix/optimize-copy":
                    self._json(optimize_copy_with_llmstudio(payload))
                    return
                if path == "/api/remix/images/polish":
                    self._json(polish_remix_images_with_codex(root, payload))
                    return
                if path == "/api/remix/images/polish-local":
                    self._json(polish_remix_images_locally(root, payload))
                    return
                if path == "/api/remix/affiliate-plan":
                    self._json(create_affiliate_remix_plan(payload.get("analysis") or payload, payload))
                    return
                if path == "/api/remix/affiliate-jianying":
                    self._json(
                        create_affiliate_jianying_handoff(
                            root,
                            payload.get("analysis") or payload,
                            payload,
                            payload.get("package_name"),
                            launch=bool(payload.get("launch")),
                        )
                    )
                    return
                if path == "/api/remix/file":
                    self._json(save_remix_package_file(root, payload.get("path", ""), payload.get("content", "")))
                    return
                if path == "/api/remix/content/delete":
                    self._json(delete_remix_content(root, str(payload.get("id") or "")))
                    return
                if path == "/api/remix/content/open-folder":
                    self._json(open_xiaohongshu_content_folder(root, str(payload.get("id") or "")))
                    return
                if path == "/api/remix/content/douyin-open-folder":
                    self._json(open_douyin_content_folder(root, str(payload.get("id") or "")))
                    return
                if path == "/api/remix/content/jianying-generate":
                    if payload.get("automation"):
                        self._json(start_jianying_automation_job(root, str(payload.get("id") or ""), launch=bool(payload.get("launch", True))))
                        return
                    self._json(start_jianying_content_generation(root, str(payload.get("id") or ""), launch=bool(payload.get("launch", True))))
                    return
                if path == "/api/remix/content/xiaohongshu-generate":
                    self._json(start_xiaohongshu_note_generation(root, str(payload.get("id") or ""), str(payload.get("source_package_path") or "")))
                    return
                if path == "/api/remix/content/douyin-generate":
                    self._json(start_douyin_note_generation(root, str(payload.get("id") or ""), str(payload.get("source_package_path") or "")))
                    return
                if path == "/api/remix/content/xiaohongshu-publish":
                    self._json(start_xiaohongshu_publish_assistant(root, str(payload.get("id") or ""), launch=bool(payload.get("launch", True))))
                    return
                if path == "/api/remix/package":
                    self._json(create_remix_package(root, payload.get("analysis") or payload, payload.get("package_name")))
                    return
                if path == "/api/remix/jianying":
                    self._json(
                        create_jianying_handoff(
                            root,
                            payload.get("analysis") or payload,
                            payload.get("package_name"),
                            launch=bool(payload.get("launch")),
                        )
                    )
                    return
                if path == "/api/projects/delete":
                    self._json(delete_projects(root, payload.get("project_ids") or []))
                    return
                if path == "/api/voice":
                    self._json(generate_voice(root, _required_text(payload, "project_id")))
                    return
                if path == "/api/align":
                    self._json(align_subtitles(root, _required_text(payload, "project_id")))
                    return
                if path == "/api/video":
                    self._json(
                        export_video(
                            root,
                            _required_text(payload, "project_id"),
                            target_duration_seconds=_target_duration_seconds(payload.get("target_duration_seconds")),
                            include_platforms=bool(payload.get("include_platforms")),
                        )
                    )
                    return
                if path == "/api/package":
                    self._json(
                        package_platform_publish(
                            root,
                            _required_text(payload, "project_id"),
                            _required_text(payload, "platform"),
                        )
                    )
                    return
                if path == "/api/performance":
                    self._json(
                        save_project_performance(
                            root,
                            _required_text(payload, "project_id"),
                            payload.get("performance") or [],
                        )
                    )
                    return
                if path == "/api/title-experiments":
                    self._json(
                        save_title_experiments(
                            root,
                            _required_text(payload, "project_id"),
                            payload.get("title_experiments") or [],
                        )
                    )
                    return
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> Dict[str, Any]:
            raw = self._read_body().decode("utf-8") if int(self.headers.get("Content-Length", "0")) else "{}"
            return json.loads(raw)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length) if length else b""

        def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            if not path.exists():
                self.send_error(404)
                return
            file_size = path.stat().st_size
            byte_range = parse_byte_range(self.headers.get("Range", ""), file_size)
            if byte_range == "invalid":
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return

            start, end = byte_range or (0, file_size - 1)
            status = 206 if byte_range else 200
            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if byte_range:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.end_headers()
            with path.open("rb") as file:
                file.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = file.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _send_project_media(self, root: Path, request_path: str) -> None:
            relative = unquote(request_path.removeprefix("/media/"))
            media_path = (root / "projects" / relative).resolve()
            projects_root = (root / "projects").resolve()
            if not str(media_path).startswith(str(projects_root)) or not media_path.exists():
                self.send_error(404)
                return
            content_type = _content_type(media_path)
            self._send_file(media_path, content_type)

        def _send_generated_file(self, root: Path, request_path: str) -> None:
            generated_path = generated_request_path(root, request_path)
            uploads_root = (root / "uploads").resolve()
            if not str(generated_path).startswith(str(uploads_root)) or not generated_path.exists():
                self.send_error(404)
                return
            self._send_file(generated_path, _content_type(generated_path))

    return WorkflowHandler


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".aiff", ".aif"}:
        return "audio/aiff"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def parse_byte_range(header: str, file_size: int) -> tuple[int, int] | str | None:
    if not header:
        return None
    if file_size <= 0:
        return "invalid"
    if not header.startswith("bytes="):
        return "invalid"
    spec = header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in spec:
        return "invalid"
    start_text, end_text = spec.split("-", 1)
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return "invalid"
            start = max(0, file_size - suffix_length)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return "invalid"
    if start < 0 or end < start or start >= file_size:
        return "invalid"
    return start, min(end, file_size - 1)


def _file_count(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for path in directory.iterdir() if path.is_file())


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def _ffmpeg_path(project_dir: Path, path: Path) -> str:
    try:
        return _relative(project_dir, path)
    except ValueError:
        return str(path)


def _script_path_from_payload(root: Path, project_id: str, payload: Dict[str, Any]) -> Path:
    script_text = str(payload.get("script_text") or "").strip()
    if not script_text and is_product_payload(payload):
        script_text = product_video_script(payload)
    if script_text:
        inbox = root / "inputs"
        inbox.mkdir(parents=True, exist_ok=True)
        script_path = inbox / f"{project_id}-{int(time.time())}.txt"
        script_path.write_text(script_text, encoding="utf-8")
        return script_path
    script_path = _optional_path(payload.get("script_path"))
    if not script_path:
        raise ValueError("请粘贴文案或填写文案文件路径")
    return script_path


def _optional_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def safe_path_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    return cleaned or "files"


def safe_filename(value: str) -> str:
    name = Path(value).name
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".", " ") else "_" for ch in name).strip()
    return cleaned or f"upload-{int(time.time() * 1000)}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一文件名: {path}")


def _required_text(payload: Dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"缺少字段: {key}")
    return value


if __name__ == "__main__":
    run_server()
