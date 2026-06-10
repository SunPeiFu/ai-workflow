from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from workflow.core import (
    build_project,
    estimate_voice_timeline,
    load_text_document,
    render_srt,
    scale_segments_to_duration,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-video-workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="检查本地依赖")
    subparsers.add_parser("voices", help="列出 macOS 可选口播声音")

    web_parser = subparsers.add_parser("web", help="启动本地前端控制台")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)

    text_parser = subparsers.add_parser("text", help="把 .txt/.md 文案规范化为纯文本")
    text_parser.add_argument("script", type=Path)

    srt_parser = subparsers.add_parser("srt", help="根据文案生成可导入剪辑软件的 SRT 字幕")
    srt_parser.add_argument("script", type=Path)
    srt_parser.add_argument("-o", "--output", type=Path, default=Path("exports/subtitles.srt"))
    srt_parser.add_argument("--chars-per-second", type=float, default=4.8)

    project_parser = subparsers.add_parser("project", help="生成一整期视频工作流项目包")
    project_parser.add_argument("--id", required=True, help="项目 ID，例如 ep001")
    project_parser.add_argument("--script", required=True, type=Path, help="长文案 .txt/.md")
    project_parser.add_argument("--voice", default="Tingting", help="macOS say 声音名")
    project_parser.add_argument("--bgm", type=Path, help="自定义 BGM 文件")
    project_parser.add_argument("--image", action="append", type=Path, default=[], help="自定义图片，可重复传入")
    project_parser.add_argument("--chars-per-second", type=float, default=4.8)

    align_parser = subparsers.add_parser("align", help="用已生成的口播音频时长校准 SRT 时间轴")
    align_parser.add_argument("--project", required=True, help="项目 ID，例如 ep001")
    align_parser.add_argument("--audio", type=Path, help="口播音频路径，默认 projects/<id>/voice/voice.aiff")
    align_parser.add_argument("--chars-per-second", type=float, default=4.8)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor()
    if args.command == "voices":
        return voices()
    if args.command == "web":
        from workflow.web_app import run_server

        run_server(host=args.host, port=args.port, root=ROOT)
        return 0
    if args.command == "text":
        print(load_text_document(args.script))
        return 0
    if args.command == "srt":
        return write_srt(args.script, args.output, args.chars_per_second)
    if args.command == "project":
        return write_project(args)
    if args.command == "align":
        return align_project(args.project, args.audio, args.chars_per_second)
    return 1


def doctor() -> int:
    checks = [
        ("python3", shutil.which("python3")),
        ("say", shutil.which("say")),
        ("ffmpeg", shutil.which("ffmpeg")),
        ("yt-dlp", shutil.which("yt-dlp")),
        ("ollama", shutil.which("ollama")),
    ]
    print("本地视频工作流依赖检查")
    for name, path in checks:
        status = "OK" if path else "MISSING"
        print(f"- {name}: {status}{' (' + path + ')' if path else ''}")
    if not shutil.which("ffmpeg"):
        print("\n建议安装: brew install ffmpeg")
    if not shutil.which("yt-dlp"):
        print("可选安装: brew install yt-dlp")
    if not shutil.which("ollama"):
        print("可选安装: brew install ollama")
    return 0


def voices() -> int:
    if not shutil.which("say"):
        print("未找到 macOS say 命令")
        return 1
    subprocess.run(["say", "-v", "?"], check=False)
    return 0


def write_srt(script: Path, output: Path, chars_per_second: float) -> int:
    text = load_text_document(script)
    srt = render_srt(estimate_voice_timeline(text, chars_per_second=chars_per_second))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(srt, encoding="utf-8")
    print(f"已生成字幕: {output}")
    return 0


def write_project(args: argparse.Namespace) -> int:
    project = build_project(
        root=ROOT,
        project_id=args.id,
        script_path=args.script,
        voice=args.voice,
        bgm=args.bgm,
        images=args.image,
        chars_per_second=args.chars_per_second,
    )
    print(f"已生成项目: {project.project_dir}")
    print(f"- 文案: {project.script_path}")
    print(f"- 字幕: {project.srt_path}")
    print(f"- 配置: {project.manifest_path}")
    print(f"- 口播生成脚本: {project.voice_command_path}")
    return 0


def align_project(project_id: str, audio: Path | None, chars_per_second: float) -> int:
    project_dir = ROOT / "projects" / project_id
    script_path = project_dir / "script.txt"
    audio_path = audio or project_dir / "voice" / "voice.aiff"
    if not script_path.exists():
        print(f"未找到项目文案: {script_path}")
        return 1
    if not audio_path.exists():
        print(f"未找到口播音频: {audio_path}")
        print("请先运行项目内的 voice/generate_voice.sh")
        return 1
    duration = audio_duration_seconds(audio_path)
    if duration is None:
        print("无法读取音频时长。macOS 可使用 afinfo；或先安装 ffmpeg。")
        return 1
    text = load_text_document(script_path)
    segments = estimate_voice_timeline(text, chars_per_second=chars_per_second)
    aligned = scale_segments_to_duration(segments, duration_seconds=duration)
    srt_path = project_dir / "exports" / "subtitles.srt"
    srt_path.write_text(render_srt(aligned), encoding="utf-8")
    print(f"已按音频时长 {duration:.3f}s 校准字幕: {srt_path}")
    return 0


def audio_duration_seconds(audio_path: Path) -> float | None:
    if shutil.which("afinfo"):
        result = subprocess.run(["afinfo", str(audio_path)], text=True, capture_output=True, check=False)
        match = re.search(r"estimated duration:\s*([0-9.]+)\s*sec", result.stdout)
        if match:
            return float(match.group(1))
    if shutil.which("ffprobe"):
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(audio_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
