from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib import request
from urllib.parse import unquote, urlparse

MAX_BGM_DOWNLOAD_BYTES = 80 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".aiff", ".aif", ".ogg", ".flac"}


@dataclass(frozen=True)
class BgmSource:
    key: str
    name: str
    url: str
    license_note: str
    best_for: str
    caution: str


BGM_SOURCES = [
    BgmSource(
        key="aigei",
        name="爱给网配乐",
        url="https://www.aigei.com/music/",
        license_note="站内有免费配乐和不同授权类型，具体以单条素材页标注为准。",
        best_for="短视频、口播、宣传片、情绪氛围和常规背景音乐。",
        caution="下载前核对是否可商用、是否要求署名、是否有平台发布限制。",
    ),
    BgmSource(
        key="ear0",
        name="耳聆网音乐素材",
        url="https://www.ear0.com/",
        license_note="中文声音分享平台，素材授权和使用条件以每条素材页为准。",
        best_for="自然氛围、环境音、音效、轻背景声和真实感素材。",
        caution="注意区分音效、音乐和环境声，发布前保存素材页与授权截图。",
    ),
    BgmSource(
        key="tosound",
        name="淘声网音乐音效",
        url="https://www.tosound.com/",
        license_note="聚合中文可检索音乐/音效资源，授权信息需进入素材详情页确认。",
        best_for="快速检索片头、转场、氛围、音效和可替代 BGM。",
        caution="聚合搜索结果来源不同，必须记录最终来源页和许可证。",
    ),
    BgmSource(
        key="freesound_cn",
        name="飞声音效配乐",
        url="https://www.freesound.cn/",
        license_note="中文免费声音素材站，单条素材会有不同使用说明。",
        best_for="短视频 BGM、音效、转场声和情绪氛围素材。",
        caution="免费不等于免审查，发布前确认商用范围和署名要求。",
    ),
]

BGM_SOURCE_KEYS = {source.key for source in BGM_SOURCES}


def bgm_source_catalog() -> List[Dict[str, str]]:
    return [asdict(source) for source in BGM_SOURCES]


def download_bgm_from_url(root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    source_key = safe_path_part(str(payload.get("source") or "library"))
    if not url:
        return {"ok": False, "error": "请粘贴中文免费 BGM 的音频下载 URL"}
    if source_key not in BGM_SOURCE_KEYS:
        return {"ok": False, "error": "请选择中文免费 BGM 素材库中的来源"}
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return {"ok": False, "error": "只支持 http/https 音频下载链接"}

    with open_without_proxy(url) as response:
        content_type = response.headers.get("Content-Type", "")
        content = response.read(MAX_BGM_DOWNLOAD_BYTES + 1)
    if len(content) > MAX_BGM_DOWNLOAD_BYTES:
        return {"ok": False, "error": "BGM 文件超过 80MB，请先手动下载后选择本地文件"}

    filename = _download_filename(payload, parsed.path, content_type)
    if Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
        return {"ok": False, "error": "下载链接不像音频文件，请使用 mp3/wav/m4a/aac/aiff/ogg/flac"}

    target_dir = root / "uploads" / "bgm-library" / source_key
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / safe_filename(filename))
    target.write_bytes(content)
    source_metadata_path(target).write_text(
        json.dumps(
            {
                "source": source_key,
                "source_url": url,
                "content_type": content_type,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "files": [
            {
                "name": target.name,
                "path": str(target),
                "source": source_key,
                "source_url": url,
                "content_type": content_type,
            }
        ],
    }


def _download_filename(payload: Dict[str, Any], url_path: str, content_type: str) -> str:
    explicit = str(payload.get("filename") or "").strip()
    if explicit:
        return explicit
    path_name = Path(unquote(url_path)).name
    if path_name and Path(path_name).suffix:
        return path_name
    if "wav" in content_type:
        return "library-bgm.wav"
    if "ogg" in content_type:
        return "library-bgm.ogg"
    if "flac" in content_type:
        return "library-bgm.flac"
    return "library-bgm.mp3"


def open_without_proxy(url: str):
    opener = request.build_opener(request.ProxyHandler({}))
    return opener.open(url, timeout=30)


def safe_path_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    return cleaned or "files"


def safe_filename(value: str) -> str:
    name = Path(value).name
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".", " ") else "_" for ch in name).strip()
    return cleaned or "library-bgm"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一文件名: {path}")


def source_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.source.json")
