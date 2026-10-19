#!/usr/bin/env python3
"""autosub - 自动识别视频/音频中的语音，生成字幕文件。

基于 faster-whisper（CPU 可跑），中文识别效果好。

用法:
    autosub video.mp4                  # 生成 video.srt（中文）
    autosub video.mp4 --lang en        # 英文
    autosub video.mp4 --model tiny     # 最快，精度稍低
    autosub video.mp4 --format vtt     # 输出 WebVTT
    autosub audio.mp3 -o sub.srt       # 指定输出
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

MODEL_SIZES = {
    'tiny': '~75MB',
    'base': '~150MB',
    'small': '~500MB',
    'medium': '~1.5GB',
}

CACHE_DIR = os.path.expanduser('~/.cache/autosub')


def check_ffmpeg():
    if not shutil.which('ffmpeg'):
        raise RuntimeError(
            '缺少 ffmpeg，请先安装：\n'
            '  Ubuntu/Debian: sudo apt install ffmpeg\n'
            '  macOS: brew install ffmpeg\n'
            '  Windows: https://ffmpeg.org/download.html'
        )


def extract_audio(video_path):
    """用 ffmpeg 从视频提取 16k 单声道 wav。"""
    fd, wav = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-i', video_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        wav,
    ]
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.exists(wav):
        raise RuntimeError('音频提取失败，请确认文件是有效的视频/音频')
    return wav


def load_wav_array(wav_path):
    """用标准库 wave 读取 pcm wav，返回 float32 numpy 数组（16k 单声道）。

    绕过 faster-whisper 内置的 PyAV 解码（av>=19 移除了 metadata_errors 参数，
    会导致 decode_audio 报错），直接传 numpy 数组给 transcribe。
    """
    import wave
    import numpy as np
    with wave.open(wav_path, 'rb') as w:
        n = w.getnframes()
        raw = w.readframes(n)
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
    if sr != 16000 or ch != 1 or sw != 2:
        raise RuntimeError(f'音频格式异常: {sr}Hz/{ch}ch/{sw*8}bit，应为 16000Hz 单声道 16bit')
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def fmt_ts(seconds, vtt=False):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if vtt:
        return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def write_srt(segments, path):
    with open(path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            f.write(f'{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{seg.text.strip()}\n\n')


def write_vtt(segments, path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('WEBVTT\n\n')
        for seg in segments:
            f.write(f'{fmt_ts(seg.start, vtt=True)} --> {fmt_ts(seg.end, vtt=True)}\n{seg.text.strip()}\n\n')


def write_txt(segments, path):
    with open(path, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(seg.text.strip() + '\n')


def resolve_model_path(model_name, cache_dir=CACHE_DIR):
    """返回 (model_path, is_bundled)。打包版自带 tiny 模型时直接用内置路径。"""
    if getattr(sys, 'frozen', False) and model_name == 'tiny':
        base = getattr(sys, '_MEIPASS', '')
        cand = os.path.join(base, 'models', 'models--Systran--faster-whisper-tiny')
        if os.path.isdir(cand):
            snaps = os.path.join(cand, 'snapshots')
            if os.path.isdir(snaps):
                subs = os.listdir(snaps)
                if subs:
                    return os.path.join(snaps, subs[0]), True
            return cand, True
    return model_name, False


def transcribe_file(input_path, lang='zh', model='small', fmt='srt',
                    device='cpu', output=None, progress=None):
    """核心转录逻辑（CLI 与 GUI 共用）。

    progress: 可选回调 progress(text)，用于报告状态。
    返回 (输出字幕路径, 字幕条数)。
    """
    def say(msg):
        if progress:
            progress(msg)

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'找不到文件: {input_path}')

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError('缺少依赖，请先运行: pip install -r requirements.txt')

    if not output:
        output = f'{os.path.splitext(input_path)[0]}.{fmt}'

    model_size = MODEL_SIZES.get(model, '')
    model_path, is_bundled = resolve_model_path(model)
    if is_bundled:
        say(f'使用内置模型 tiny（{model_size}），无需下载')
    else:
        say(f'加载模型 {model}（{model_size}），首次运行会自动下载到 {CACHE_DIR} …')
        os.makedirs(CACHE_DIR, exist_ok=True)
    wm = WhisperModel(model_path, device=device, download_root=CACHE_DIR)

    say('提取音频…')
    wav = extract_audio(input_path)
    try:
        say('识别中…')
        audio = load_wav_array(wav)
        segments, info = wm.transcribe(audio, language=lang, beam_size=5)
        segments = list(segments)
        say(f'检测到语言: {info.language}'
            f'（置信度 {info.language_probability:.2f}），共 {len(segments)} 条字幕')
    finally:
        os.unlink(wav)

    if not segments:
        raise RuntimeError('未识别出任何语音')

    if fmt == 'vtt':
        write_vtt(segments, output)
    elif fmt == 'txt':
        write_txt(segments, output)
    else:
        write_srt(segments, output)

    say(f'字幕已保存: {output}')
    return output, len(segments)


def main():
    ap = argparse.ArgumentParser(
        description='自动识别视频/音频中的语音，生成字幕（中文为主）')
    ap.add_argument('input', help='视频/音频文件路径')
    ap.add_argument('-o', '--output', help='输出字幕路径（默认与输入同名）')
    ap.add_argument('--lang', default='zh',
                    help='语言代码，如 zh/en/ja，默认 zh（中文）')
    ap.add_argument('--model', default='small',
                    choices=['tiny', 'base', 'small', 'medium'],
                    help='模型大小，默认 small（精度/速度平衡）')
    ap.add_argument('--format', default='srt', choices=['srt', 'vtt', 'txt'],
                    help='输出格式，默认 srt')
    ap.add_argument('--device', default='cpu', choices=['cpu', 'cuda'],
                    help='运行设备，默认 cpu')
    args = ap.parse_args()

    try:
        check_ffmpeg()
    except RuntimeError as e:
        sys.exit(str(e))

    def say(msg):
        print(msg, flush=True)

    try:
        out, n = transcribe_file(
            args.input, lang=args.lang, model=args.model, fmt=args.format,
            device=args.device, output=args.output, progress=say)
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(str(e))
    print(f'完成，共 {n} 条字幕: {out}')


if __name__ == '__main__':
    main()
