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
        sys.exit(
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
        sys.exit('音频提取失败，请确认文件是有效的视频/音频')
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
        sys.exit(f'音频格式异常: {sr}Hz/{ch}ch/{sw*8}bit，应为 16000Hz 单声道 16bit')
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

    if not os.path.isfile(args.input):
        sys.exit(f'找不到文件: {args.input}')

    check_ffmpeg()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit('缺少依赖，请先运行: pip install -r requirements.txt')

    out = args.output
    if not out:
        base = os.path.splitext(args.input)[0]
        out = f'{base}.{args.format}'

    model_size = MODEL_SIZES.get(args.model, '')

    # 打包版自带 tiny 模型：优先用内置的，无需下载
    model_path = args.model
    bundled = None
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', '')
        cand = os.path.join(base, 'models', 'models--Systran--faster-whisper-tiny')
        # 兼容直接放 snapshot 的结构
        if os.path.isdir(cand):
            # 找 snapshot 下的实际模型目录
            snaps = os.path.join(cand, 'snapshots')
            if os.path.isdir(snaps):
                subs = os.listdir(snaps)
                if subs:
                    bundled = os.path.join(snaps, subs[0])
            else:
                bundled = cand
    if bundled and args.model == 'tiny':
        print(f'使用内置模型 tiny（{model_size}），无需下载', flush=True)
        model_path = bundled
    else:
        print(f'加载模型 {args.model}（{model_size}），首次运行会自动下载到 {CACHE_DIR} …',
              flush=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
    model = WhisperModel(model_path, device=args.device,
                         download_root=CACHE_DIR)

    print('提取音频…', flush=True)
    wav = extract_audio(args.input)
    try:
        print('识别中…', flush=True)
        audio = load_wav_array(wav)
        segments, info = model.transcribe(audio, language=args.lang, beam_size=5)
        segments = list(segments)
        print(f'检测到语言: {info.language}（置信度 {info.language_probability:.2f}），'
              f'共 {len(segments)} 条字幕', flush=True)
    finally:
        os.unlink(wav)

    if not segments:
        sys.exit('未识别出任何语音')

    if args.format == 'vtt':
        write_vtt(segments, out)
    elif args.format == 'txt':
        write_txt(segments, out)
    else:
        write_srt(segments, out)

    print(f'字幕已保存: {out}')


if __name__ == '__main__':
    main()
