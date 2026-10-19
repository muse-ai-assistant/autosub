# autosub 🎙️

Auto-generate subtitles from video/audio speech. Chinese-first, powered by faster-whisper. Runs on CPU, fully offline after the first model download.

自动识别视频/音频中的语音生成字幕（中文为主），基于 faster-whisper，CPU 可跑，模型下载后纯离线。

## 痛点 / Why

给视频配字幕是创作者的高频刚需：剪辑完的视频没有字幕，手动打轴又慢又累。autosub 一行命令搞定——扔个视频进去，出来 srt 字幕文件。

## 安装 / Install

需要 Python 3.9+ 和 ffmpeg：

```bash
# Ubuntu/Debian
sudo apt install ffmpeg
# macOS
brew install ffmpeg
```

```bash
pip install -r requirements.txt
```

> 📦 **开箱即用**：不想装 Python 的直接下载单文件版
> https://github.com/muse-ai-assistant/autosub/releases/latest
> （仍需系统安装 ffmpeg；首次运行自动下载语音模型）

> 首次运行时会自动下载语音模型到 `~/.cache/autosub/`（tiny ~75MB / base ~150MB / small ~500MB / medium ~1.5GB）。

## 用法 / Usage

### 图形界面（推荐，不用记命令）/ GUI

```bash
python autosub_gui.py
```

选文件 → 选模型/语言/格式 → 点「开始生成字幕」，完成后点「打开所在文件夹」取字幕。

### 命令行 / CLI

```bash
# 基本：video.mp4 -> video.srt（中文）
autosub video.mp4

# 指定语言
autosub video.mp4 --lang en

# 换模型（tiny 最快，medium 最准，默认 small）
autosub video.mp4 --model tiny

# 输出 WebVTT / 纯文本
autosub video.mp4 --format vtt
autosub video.mp4 --format txt

# 指定输出路径
autosub video.mp4 -o sub.srt

# 音频文件也行
autosub podcast.mp3
```

## 说明 / Notes

- 默认中文（`--lang zh`），支持 en/ja 等（whisper 语言代码）
- 识别在 CPU 上运行，tiny 模型几分钟视频约 tens of seconds
- 有 GPU 可加 `--device cuda` 加速（需安装 CUDA 版 ctranslate2）
- 音频通过 ffmpeg 提取为 16k 单声道 wav 后识别

## License

MIT
