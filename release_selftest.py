"""Packaged UI/worker/MP3 diagnostic; may download FFmpeg from PyPI on first use."""
import functools
import http.server
import json
import tempfile
import threading
import time
import wave
from pathlib import Path

import webview

from desktop_api import DesktopAPI
from music_core import search_tracks


def run(report_path):
    report = {"ok": False}
    with tempfile.TemporaryDirectory(prefix="musicdrive-release-check-") as temporary:
        root = Path(temporary)
        with wave.open(str(root / "test.wav"), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            audio.writeframes(b"\0\0" * 22050)

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        import os
        import sys
        if getattr(sys, 'frozen', False):
            os.environ['LOCALAPPDATA'] = str(root / 'appdata')
            cache = Path(os.environ['LOCALAPPDATA']) / 'MusicDownloader' / 'tools'
            cache.mkdir(parents=True, exist_ok=True)
            (cache / 'download-consent').touch()
        api = DesktopAPI()
        api._settings = {"folder": str(root / "output"), "quality": "192", "ascii_names": False, "source": "YouTube"}
        window = webview.create_window("Music / Drive — offline self-test", url=str(Path(__file__).parent / "web" / "index.html"),
                                       width=1280, height=850)
        window.expose(api.get_state, api.set_selected, api.start_download)
        api._window = window

        def wait_for(script, timeout=15):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if window.evaluate_js(script):
                    return
                time.sleep(0.1)
            raise RuntimeError("UI condition timed out: " + script)

        def check():
            try:
                wait_for("!!window.pywebview?.api?.get_state && !document.getElementById('search-input').disabled")
                report["renderer"] = window.evaluate_js("navigator.userAgent")
                report["clipboard"] = window.evaluate_js("isSecureContext && !!navigator.clipboard")
                tracks = search_tracks(f"http://127.0.0.1:{server.server_port}/test.wav", "YouTube")
                if len(tracks) != 1:
                    raise RuntimeError("Local audio extraction failed")
                with api._lock:
                    api._results = tracks
                    api._changed()
                wait_for("!!document.querySelector('.track-select')")
                window.evaluate_js("document.querySelector('.track-select').click()")
                wait_for("document.getElementById('basket-count').textContent === '1'")
                window.evaluate_js("document.getElementById('download-button').click()")
                wait_for("document.getElementById('dock-title').textContent === 'Музыка сохранена'", timeout=100)
                files = list((root / "output").glob("*.mp3"))
                if len(files) != 1 or files[0].read_bytes()[:4] != b"ID3\x03":
                    raise RuntimeError("Expected MP3 with ID3v2.3 not generated")
                report.update({"ok": True, "mp3_bytes": files[0].stat().st_size, "summary": api.get_state()["summary"]})
            except Exception as error:
                report["error"] = str(error)
            finally:
                Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                window.destroy()

        timer = threading.Timer(130, window.destroy)
        timer.start()
        try:
            webview.start(check, gui="edgechromium", debug=False)
        finally:
            timer.cancel()
            server.shutdown()
            server.server_close()
    if not report["ok"]:
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(report.get("error", "Self-test did not complete"))
