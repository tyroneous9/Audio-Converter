"""YouTube audio downloader GUI, wrapping the yt-dlp CLI.

Updates yt-dlp on launch, lets the user paste a list of links, downloads
them as audio, and streams all terminal output to both the GUI and log.log.
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tomllib
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import tomli_w

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.toml"
LOG_PATH = BASE_DIR / "log.log"

DEFAULT_CONFIG = {"output_dir": str(Path.home() / "Downloads")}

# Subprocess creation flags to suppress console windows popping up on Windows.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def load_config():
    if CONFIG_PATH.exists():
        try:
            data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config = dict(DEFAULT_CONFIG)
            if isinstance(data, dict) and data.get("output_dir"):
                config["output_dir"] = data["output_dir"]
            return config
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    CONFIG_PATH.write_bytes(tomli_w.dumps(config).encode("utf-8"))


def find_ytdlp():
    found = shutil.which("yt-dlp")
    if found:
        return found
    local = BASE_DIR / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if local.exists():
        return str(local)
    return None


def find_ffmpeg():
    """Return a directory containing ffmpeg/ffprobe, preferring the copy bundled with the app."""
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if (BASE_DIR / exe_name).exists():
        return str(BASE_DIR)
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).resolve().parent)
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Audio Downloader")
        self.geometry("820x640")
        self.minsize(600, 480)

        self.config_data = load_config()
        self.output_queue = queue.Queue()
        self.process = None
        self.worker_thread = None

        self._build_ui()
        self.after(200, self.run_update_check)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        output_frame = ttk.Frame(self)
        output_frame.pack(fill="x", **pad)
        ttk.Label(output_frame, text="Output folder:").pack(side="left")
        self.output_var = tk.StringVar(value=self.config_data["output_dir"])
        ttk.Entry(output_frame, textvariable=self.output_var).pack(
            side="left", fill="x", expand=True, padx=(6, 6)
        )
        ttk.Button(output_frame, text="Browse...", command=self.browse_output_dir).pack(
            side="left"
        )

        links_frame = ttk.Frame(self)
        links_frame.pack(fill="both", expand=True, **pad)
        ttk.Label(links_frame, text="YouTube links (one per line):").pack(anchor="w")
        self.links_text = ScrolledText(links_frame, height=10, wrap="none")
        self.links_text.pack(fill="both", expand=True)

        controls_frame = ttk.Frame(self)
        controls_frame.pack(fill="x", **pad)
        self.run_button = ttk.Button(controls_frame, text="Run", command=self.start_download)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls_frame, text="Stop", command=self.stop_download, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(6, 0))
        self.status_var = tk.StringVar(value="Checking for yt-dlp updates...")
        ttk.Label(controls_frame, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, **pad)
        ttk.Label(log_frame, text="Output log:").pack(anchor="w")
        self.log_text = ScrolledText(log_frame, height=16, state="disabled", wrap="none")
        self.log_text.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def browse_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()))
        if chosen:
            self.output_var.set(chosen)
            self.config_data["output_dir"] = chosen
            save_config(self.config_data)

    # -- Logging ------------------------------------------------------------

    def log_line(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        try:
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def log_header(self, title):
        banner = f"\n===== {title} — {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n"
        self.log_line(banner)

    # -- Update-on-launch -----------------------------------------------

    def run_update_check(self):
        ytdlp = find_ytdlp()
        if not ytdlp:
            self.status_var.set("yt-dlp not found on PATH")
            self.log_header("yt-dlp not found")
            self.log_line(
                "Could not find 'yt-dlp' on PATH or next to this app. "
                "Install it and restart.\n"
            )
            return
        self.run_button.configure(state="disabled")
        thread = threading.Thread(
            target=self._update_worker, args=(ytdlp,), daemon=True
        )
        thread.start()
        self.after(50, self._poll_update_queue)

    def _update_worker(self, ytdlp):
        self.output_queue.put(("header", "yt-dlp self-update"))
        try:
            proc = subprocess.Popen(
                [ytdlp, "--update"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                self.output_queue.put(("line", line))
            proc.wait()
        except OSError as e:
            self.output_queue.put(("line", f"Failed to run yt-dlp --update: {e}\n"))
        self.output_queue.put(("update_done", None))

    def _poll_update_queue(self):
        done = False
        try:
            while True:
                kind, payload = self.output_queue.get_nowait()
                if kind == "line":
                    self.log_line(payload)
                elif kind == "header":
                    self.log_header(payload)
                elif kind == "update_done":
                    done = True
        except queue.Empty:
            pass
        if done:
            self.status_var.set("Ready")
            self.run_button.configure(state="normal")
        else:
            self.after(50, self._poll_update_queue)

    # -- Download run -----------------------------------------------------

    def start_download(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return

        ytdlp = find_ytdlp()
        if not ytdlp:
            messagebox.showerror("yt-dlp not found", "Could not find yt-dlp on PATH.")
            return

        links = [
            line.strip()
            for line in self.links_text.get("1.0", "end").splitlines()
            if line.strip()
        ]
        if not links:
            messagebox.showwarning("No links", "Enter at least one YouTube link.")
            return

        output_dir = self.output_var.get().strip() or DEFAULT_CONFIG["output_dir"]
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Invalid output folder", str(e))
            return
        self.config_data["output_dir"] = output_dir
        save_config(self.config_data)

        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir:
            messagebox.showwarning(
                "ffmpeg not found",
                "Could not find ffmpeg next to this app or on PATH. "
                "Audio extraction will likely fail.",
            )

        args = [
            ytdlp,
            "--cookies-from-browser", "firefox",
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "m4a",
            "--audio-quality", "192K",
            "-o", "%(title)s.%(ext)s",
            "-P", output_dir,
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
        ]
        if ffmpeg_dir:
            args += ["--ffmpeg-location", ffmpeg_dir]
        args += links

        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Downloading...")
        self.log_header(f"Run started ({len(links)} link(s))")
        if ffmpeg_dir:
            self.log_line(f"Using ffmpeg from: {ffmpeg_dir}\n")

        self.worker_thread = threading.Thread(
            target=self._download_worker, args=(args,), daemon=True
        )
        self.worker_thread.start()
        self.after(50, self._poll_download_queue)

    def _download_worker(self, args):
        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in self.process.stdout:
                self.output_queue.put(("line", line))
            returncode = self.process.wait()
        except OSError as e:
            self.output_queue.put(("line", f"Failed to run yt-dlp: {e}\n"))
            returncode = -1
        finally:
            self.process = None
        self.output_queue.put(("run_done", returncode))

    def _poll_download_queue(self):
        finished = None
        try:
            while True:
                kind, payload = self.output_queue.get_nowait()
                if kind == "line":
                    self.log_line(payload)
                elif kind == "run_done":
                    finished = payload
        except queue.Empty:
            pass

        if finished is not None:
            self.log_header(f"Run finished (exit code {finished})")
            self.status_var.set("Ready")
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        else:
            self.after(50, self._poll_download_queue)

    def stop_download(self):
        if self.process:
            self.process.terminate()
            self.status_var.set("Stopping...")

    def on_close(self):
        if self.process:
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
