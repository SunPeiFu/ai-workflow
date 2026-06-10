# 本地视频工作流使用说明

这个目录是一套本地优先的视频口播工作流。它接收长文案 `.txt`/`.md`/`.docx`，生成纯文本、口播生成脚本、同步字幕、素材目录和 DaVinci Resolve 导入说明。

## 快速开始

```bash
make doctor
make voices
make web
make project SCRIPT=samples/demo_script.txt PROJECT=ep001 VOICE=Tingting
projects/ep001/voice/generate_voice.sh
make align PROJECT=ep001
```

生成后打开 `projects/ep001/README.md`，按说明把 `voice/voice.aiff`、`exports/subtitles.srt`、图片和 BGM 导入 DaVinci Resolve。

## 常用命令

- `make text SCRIPT=你的文案.txt`：输出规范化纯文本。
- `make srt SCRIPT=你的文案.txt`：生成 `exports/subtitles.srt`。
- `make project SCRIPT=你的文案.txt PROJECT=ep002 VOICE=Tingting`：生成完整项目包。
- `make project SCRIPT=你的文案.txt PROJECT=ep002 VOICE=Tingting BGM=/path/music.mp3 IMAGE=/path/image.png`：导入自定义 BGM 和图片。
- `make align PROJECT=ep002`：在生成真实口播音频后，用音频真实时长校准字幕。
- `make web`：启动本地前端控制台，浏览器打开 `http://127.0.0.1:8765`。页面里的 BGM 支持“中文免费 BGM 库”和“本地音频文件”两种入口。
- `make voices`：查看 macOS 当前可用的口播声音。

## 当前能力

- 支持长文案 `.txt`、`.md`、`.docx` 输入。
- 自动规范化为纯文本。
- 可选择 macOS `say` 的口播声音。
- 根据文案长度估算口播时间轴并生成 SRT，字幕与口播脚本保持同源。
- 可从中文免费 BGM 素材库粘贴音频 URL 导入，也可选择本地音频文件。
- 可导入自定义图片，并复制到项目素材目录。
- 前端可点击“播放预览”，在浏览器里同步播放口播、字幕和图片轮换。

## 生成文件在哪里

- 口播音频：`projects/<项目ID>/voice/voice.aiff`
- 字幕文件：`projects/<项目ID>/exports/subtitles.srt`
- 图片素材：`projects/<项目ID>/assets/images/`
- BGM 素材：`projects/<项目ID>/assets/bgm/`
- 素材授权台账：`projects/<项目ID>/assets/licenses.md`

当前页面可导出带 ASS 硬字幕的 MP4，并生成 B 站 / 小红书 / 抖音发布包。使用中文免费 BGM 库时，请保存原素材页并复核具体曲目的许可证。

## 后续可增强

- 接入 `mlx-whisper`，用真实口播音频反向校准字幕时间轴。
- 接入 `ffmpeg`，自动把图片、口播、BGM 和字幕合成为预览视频。
- 接入 Ollama，本地生成脚本拆段、分镜和素材建议。
