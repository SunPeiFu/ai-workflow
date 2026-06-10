.PHONY: doctor voices test text srt project align web setup

PYTHON ?= python3
SCRIPT ?= samples/demo_script.txt
PROJECT ?= demo
VOICE ?= jianying-calm-male
BGM ?=
IMAGE ?=

doctor:
	$(PYTHON) -m workflow.cli doctor

voices:
	$(PYTHON) -m workflow.cli voices

test:
	$(PYTHON) -m unittest discover -s tests -v

text:
	$(PYTHON) -m workflow.cli text "$(SCRIPT)"

srt:
	$(PYTHON) -m workflow.cli srt "$(SCRIPT)" -o "exports/subtitles.srt"

project:
	$(PYTHON) -m workflow.cli project --id "$(PROJECT)" --script "$(SCRIPT)" --voice "$(VOICE)" $(if $(BGM),--bgm "$(BGM)",) $(if $(IMAGE),--image "$(IMAGE)",)

align:
	$(PYTHON) -m workflow.cli align --project "$(PROJECT)"

web:
	$(PYTHON) -m workflow.cli web --host 127.0.0.1 --port 8765

setup:
	@echo "基础可选依赖安装命令："
	@echo "  brew install ffmpeg yt-dlp ollama"
	@echo "  python3 -m pip install --user edge-tts"
	@echo "  pipx/uv 可按你的 Python 环境另行安装。"
