"""Isolated yt-dlp process so Stop can close network and FFmpeg resources."""
import contextlib
import json
import sys
import time
from pathlib import Path

import yt_dlp

from music_core import ydl_options


def emit(event, value):
    sys.__stdout__.write(json.dumps({"event": event, "value": value}, ensure_ascii=True) + "\n")
    sys.__stdout__.flush()


def main():
    request = json.loads(sys.stdin.readline())
    last_update = 0.0

    def hook(data):
        nonlocal last_update
        if data.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - last_update < 0.15:
            return
        last_update = now
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        fraction = min(data.get("downloaded_bytes", 0) / total, 1) if total else 0
        speed = data.get("speed")
        detail = f" · {speed / 1024 / 1024:.1f} МБ/с" if speed else ""
        emit("progress", [fraction * 0.8, "Скачивание" + detail])

    options = ydl_options()
    options.update({
        "format": "bestaudio/best",
        "ffmpeg_location": request["ffmpeg"],
        "outtmpl": str(Path(request["temporary"]) / "source.%(ext)s"),
        "progress_hooks": [hook],
        "max_filesize": 1024 * 1024 * 1024,
    })
    try:
        with contextlib.redirect_stdout(sys.stderr), yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(request["url"], download=True)
            if not info:
                raise RuntimeError("Площадка не вернула аудио.")
            if info.get("_type") in ("playlist", "multi_video"):
                raise ValueError("Скачивание плейлистов не поддерживается.")
            source = Path(ydl.prepare_filename(info))
            if not source.is_file():
                raise RuntimeError("Аудиофайл не получен. Возможно, трек недоступен.")
            metadata = {key: info.get(key) for key in ("track", "title", "artist", "uploader")}
        emit("done", {"source": str(source), "metadata": metadata})
    except Exception as error:
        emit("error", str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
