#!/usr/bin/env python3
"""autosub 图形界面 — 选文件、点开始，自动生成字幕。

用法:
    python autosub_gui.py
"""
import os
import queue
import subprocess
import sys
import threading

import customtkinter as ctk

import autosub

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MODEL_OPTIONS = [
    ("tiny（最快 · ~75MB）", "tiny"),
    ("base（较快 · ~150MB）", "base"),
    ("small（推荐 · ~500MB）", "small"),
    ("medium（最准 · ~1.5GB）", "medium"),
]

LANG_OPTIONS = [
    ("中文", "zh"),
    ("英文", "en"),
    ("自动检测", None),
]

FILE_TYPES = [
    ("视频/音频文件", "*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac"),
    ("所有文件", "*.*"),
]


def open_folder(path):
    folder = os.path.dirname(os.path.abspath(path))
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("autosub — 视频自动字幕")
        self.geometry("560x660")
        self.resizable(False, False)

        self.input_path = ctk.StringVar(value="")
        self.model_var = ctk.StringVar(value=MODEL_OPTIONS[2][0])  # small
        self.lang_var = ctk.StringVar(value=LANG_OPTIONS[0][0])    # 中文
        self.fmt_var = ctk.StringVar(value="srt")
        self.status_var = ctk.StringVar(value="请选择视频/音频文件")
        self.result_path = None
        self.running = False
        self._queue = queue.Queue()
        self._poll_id = None

        self._build()
        self._poll_queue()  # 主线程轮询后台消息（线程安全）

    def _build(self):
        # 标题
        ctk.CTkLabel(self, text="🎬 autosub 视频自动字幕",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self, text="自动识别语音，生成字幕文件",
                     font=ctk.CTkFont(size=13),
                     text_color="gray").pack(pady=(0, 20))

        # 文件选择
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.pack(fill="x", padx=28, pady=8)
        ctk.CTkLabel(file_frame, text="视频 / 音频文件",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        row = ctk.CTkFrame(file_frame, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self.file_entry = ctk.CTkEntry(row, textvariable=self.input_path,
                                      placeholder_text="点击右侧按钮选择文件…",
                                      state="readonly", width=380)
        self.file_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="选择文件", width=100,
                      command=self.choose_file).pack(side="left")

        # 模型选择
        opt_frame = ctk.CTkFrame(self, fg_color="transparent")
        opt_frame.pack(fill="x", padx=28, pady=8)
        ctk.CTkLabel(opt_frame, text="识别模型",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        ctk.CTkOptionMenu(opt_frame, variable=self.model_var,
                          values=[label for label, _ in MODEL_OPTIONS],
                          width=300).pack(anchor="w", pady=6)

        # 语言 + 格式
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=28, pady=8)
        left = ctk.CTkFrame(row2, fg_color="transparent")
        left.pack(side="left", padx=(0, 30))
        ctk.CTkLabel(left, text="语言",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        ctk.CTkOptionMenu(left, variable=self.lang_var,
                          values=[label for label, _ in LANG_OPTIONS],
                          width=180).pack(anchor="w", pady=6)

        right = ctk.CTkFrame(row2, fg_color="transparent")
        right.pack(side="left")
        ctk.CTkLabel(right, text="输出格式",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        ctk.CTkSegmentedButton(right, variable=self.fmt_var,
                               values=["srt", "vtt", "txt"]).pack(anchor="w", pady=6)

        # 开始按钮
        self.start_btn = ctk.CTkButton(
            self, text="▶  开始生成字幕", font=ctk.CTkFont(size=18, weight="bold"),
            height=56, command=self.start)
        self.start_btn.pack(fill="x", padx=28, pady=(16, 8))

        # 进度 + 状态
        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=28, pady=8)
        self.progress.set(0)
        ctk.CTkLabel(self, textvariable=self.status_var, wraplength=500,
                     font=ctk.CTkFont(size=13)).pack(padx=28, pady=4)

        # 结果区
        self.result_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.result_label = ctk.CTkLabel(self.result_frame, text="",
                                         wraplength=480,
                                         font=ctk.CTkFont(size=13))
        self.result_label.pack()
        self.open_btn = ctk.CTkButton(self.result_frame, text="📂 打开所在文件夹",
                                     command=self.open_result_folder)

    def choose_file(self):
        if self.running:
            return
        path = ctk.filedialog.askopenfilename(title="选择视频/音频文件",
                                              filetypes=FILE_TYPES)
        if path:
            self.input_path.set(path)
            self.status_var.set("已选择文件，点击「开始生成字幕」")
            self.result_frame.pack_forget()

    def _set_status(self, text):
        # 后台线程调用：只往队列里放，主线程负责更新界面
        self._queue.put(("status", text))

    def _poll_queue(self):
        """主线程定时轮询后台线程的消息，线程安全。"""
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "done":
                    self._done(msg[1], msg[2])
                elif kind == "error":
                    self._failed(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def start(self):
        if self.running:
            return
        path = self.input_path.get().strip()
        if not path or not os.path.isfile(path):
            self.status_var.set("⚠️ 请先选择有效的视频/音频文件")
            return
        try:
            autosub.check_ffmpeg()
        except RuntimeError as e:
            self.status_var.set(f"⚠️ {e}")
            return

        model = dict((l, v) for l, v in MODEL_OPTIONS)[self.model_var.get()]
        lang = dict((l, v) for l, v in LANG_OPTIONS)[self.lang_var.get()]
        fmt = self.fmt_var.get()

        self.running = True
        self.start_btn.configure(state="disabled", text="⏳ 生成中…")
        self.result_frame.pack_forget()
        self.progress.start()

        t = threading.Thread(target=self._worker,
                             args=(path, lang, model, fmt), daemon=True)
        t.start()

    def _worker(self, path, lang, model, fmt):
        try:
            out, n = autosub.transcribe_file(
                path, lang=lang, model=model, fmt=fmt,
                progress=self._set_status)
            self._queue.put(("done", out, n))
        except Exception as e:  # noqa: BLE001
            self._queue.put(("error", str(e)))

    def _done(self, out, n):
        self.running = False
        self.progress.stop()
        self.progress.set(1)
        self.start_btn.configure(state="normal", text="▶  开始生成字幕")
        self.status_var.set(f"✅ 完成！共生成 {n} 条字幕")
        self.result_path = out
        self.result_label.configure(text=f"字幕已保存：\n{out}")
        self.open_btn.pack(pady=(8, 0))
        self.result_frame.pack(fill="x", padx=28, pady=8)

    def _failed(self, msg):
        self.running = False
        self.progress.stop()
        self.progress.set(0)
        self.start_btn.configure(state="normal", text="▶  开始生成字幕")
        self.status_var.set(f"❌ 失败：{msg}")

    def open_result_folder(self):
        if self.result_path:
            open_folder(self.result_path)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
