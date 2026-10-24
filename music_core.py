from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import imageio_ffmpeg
import yt_dlp
from unidecode import unidecode


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "MusicDownloader"
DEFAULT_FOLDER = Path.home() / "Music" / "MusicDownloader"
QUALITIES = ("128", "192", "256", "320")


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    duration: float | None
    url: str
    identifier: str


class Cancelled(Exception):
    pass


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def load_settings(path: Path | None = None) -> dict:
    defaults = {"folder": str(DEFAULT_FOLDER), "quality": "192", "ascii_names": False, "source": "YouTube"}
    try:
        data = json.loads((path or APP_DIR / "settings.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        if isinstance(data.get("folder"), str) and data["folder"].strip():
            defaults["folder"] = data["folder"]
        if data.get("quality") in QUALITIES:
            defaults["quality"] = data["quality"]
        if isinstance(data.get("ascii_names"), bool):
            defaults["ascii_names"] = data["ascii_names"]
        if data.get("source") in ("YouTube", "SoundCloud"):
            defaults["source"] = data["source"]
    except (OSError, ValueError):
        pass
    return defaults


def save_settings(settings: dict, path: Path | None = None) -> None:
    target = path or APP_DIR / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def safe_filename(title: str, ascii_names: bool = False) -> str:
    if ascii_names:
        title = unidecode(title)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    title = re.sub(r"\s+", " ", title).strip(" .")[:120].rstrip(" .")
    if not title:
        title = "Track"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", title, re.I):
        title = "_" + title
    return title


def duration_text(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def search_target(query: str, source: str, limit: int = 15) -> str:
    query = query.strip()
    if not query:
        raise ValueError("Введите название песни или ссылку.")
    parsed = urlparse(query)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return query
    if "://" in query or query.lower().startswith(("file:", "ytsearch", "scsearch")):
        raise ValueError("Введите название песни либо обычную HTTP/HTTPS-ссылку.")
    return f"{'scsearch' if source == 'SoundCloud' else 'ytsearch'}{limit}:{query}"


def ydl_options() -> dict:
    runtimes = {}
    for name in ("deno", "node"):
        executable = shutil.which(name)
        if executable:
            runtimes[name] = {"path": executable}
    return {
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLogger(),
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "extractor_retries": 2,
        "js_runtimes": runtimes,
    }


def search_tracks(query: str, source: str) -> list[Track]:
    options = ydl_options()
    options.update({"extract_flat": "in_playlist", "playlistend": 15, "skip_download": True})
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(search_target(query, source), download=False)
    if not info:
        return []
    if info.get("_type") in ("playlist", "multi_video"):
        # Search results are playlists internally; arbitrary playlists are not supported.
        if urlparse(query.strip()).scheme in ("http", "https"):
            raise ValueError("Вставьте ссылку на отдельный трек, а не на плейлист.")
        entries = info.get("entries") or []
    else:
        entries = [info]
    tracks = []
    seen = set()
    for item in entries:
        if not item or item.get("is_live") or item.get("live_status") in ("is_live", "is_upcoming"):
            continue
        url = item.get("webpage_url") or item.get("url", "")
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        tracks.append(Track(
            title=item.get("title") or "Без названия",
            artist=item.get("artist") or item.get("uploader") or item.get("channel") or "Неизвестный исполнитель",
            duration=item.get("duration"),
            url=url,
            identifier=str(item.get("id") or "track"),
        ))
    return tracks


def unique_destination(folder: Path, stem: str) -> Path:
    candidate = folder / f"{stem}.mp3"
    index = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({index}).mp3"
        index += 1
    return candidate


def terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def fetch_audio(
    url: str, temporary: Path, ffmpeg: str, cancel: threading.Event,
    progress: Callable[[float, str], None],
) -> tuple[Path, dict]:
    messages = queue.Queue()
    popen_options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (temporary / "download.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("download_worker.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding="utf-8", **popen_options,
        )

        def read_messages():
            try:
                for line in process.stdout:
                    try:
                        messages.put(json.loads(line))
                    except ValueError:
                        pass
            finally:
                messages.put(None)

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        result = None
        error = None
        try:
            process.stdin.write(json.dumps({"url": url, "temporary": str(temporary), "ffmpeg": ffmpeg}) + "\n")
            process.stdin.close()
            ended = False
            while not ended:
                if cancel.is_set():
                    raise Cancelled()
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if message is None:
                    ended = True
                elif message.get("event") == "progress":
                    progress(*message["value"])
                elif message.get("event") == "done":
                    result = message["value"]
                elif message.get("event") == "error":
                    error = message["value"]
            process.wait()
            if error:
                raise RuntimeError(error)
            if process.returncode or not result:
                details = (temporary / "download.log").read_text(encoding="utf-8", errors="replace")
                raise RuntimeError("Не удалось загрузить аудио. " + details[-1500:])
            return Path(result["source"]), result["metadata"]
        finally:
            try:
                terminate_process_tree(process)
            finally:
                if not process.stdin.closed:
                    process.stdin.close()
                reader.join(timeout=5)
                process.stdout.close()


def download_track(
    track: Track,
    folder: Path,
    quality: str,
    ascii_names: bool,
    cancel: threading.Event,
    progress: Callable[[float, str], None],
) -> Path:
    if quality not in QUALITIES:
        raise ValueError("Неподдерживаемый битрейт.")
    if cancel.is_set():
        raise Cancelled()
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    # Temporary media stays off the USB drive; only the completed MP3 is copied there.
    with tempfile.TemporaryDirectory(prefix="musicdownloader-") as temporary:
        temp = Path(temporary)
        source, info = fetch_audio(track.url, temp, ffmpeg, cancel, progress)
        if cancel.is_set():
            raise Cancelled()
        progress(0.82, "Преобразование в MP3…")
        converted = temp / "output.mp3"
        title = str(info.get("track") or info.get("title") or track.title)
        artist = str(info.get("artist") or info.get("uploader") or track.artist)
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-map_metadata", "-1",
            "-c:a", "libmp3lame", "-b:a", f"{quality}k", "-ar", "44100", "-ac", "2",
            "-id3v2_version", "3", "-write_id3v1", "1",
            "-metadata", f"title={title}", "-metadata", f"artist={artist}",
            str(converted),
        ]
        with (temp / "ffmpeg.log").open("wb") as log:
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while process.poll() is None:
                    if cancel.wait(0.15):
                        raise Cancelled()
                if process.returncode:
                    message = (temp / "ffmpeg.log").read_text(encoding="utf-8", errors="replace")
                    raise RuntimeError("Ошибка преобразования MP3: " + message[-1200:])
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        if cancel.is_set():
            raise Cancelled()
        if not converted.is_file() or not converted.stat().st_size:
            raise RuntimeError("Получился пустой MP3-файл.")
        progress(0.96, "Сохранение в выбранную папку…")
        destination = unique_destination(folder, safe_filename(track.title, ascii_names))
        # Exclusive creation avoids overwriting an existing file, even on a collision.
        created = False
        try:
            with destination.open("xb") as output, converted.open("rb") as input_file:
                created = True
                while chunk := input_file.read(1024 * 1024):
                    if cancel.is_set():
                        raise Cancelled()
                    output.write(chunk)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        progress(1, "Готово")
        return destination


def friendly_error(error: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(error))
    lower = text.lower()
    if any(word in lower for word in ("sign in", "bot", "javascript", "js runtime", "challenge", "403")):
        return ("Площадка ограничила доступ. Запустите update.bat; для YouTube установите Deno "
                "(инструкция в README), затем перезапустите приложение. Можно попробовать SoundCloud.\n\n" + text)
    if any(word in lower for word in ("timed out", "unable to download", "connection", "getaddrinfo")):
        return "Не удалось подключиться к площадке. Проверьте интернет и доступность сайта.\n\n" + text
    if "no space" in lower or "disk full" in lower:
        return "Недостаточно места на диске или флешке.\n\n" + text
    return text or type(error).__name__
