import functools
import http.server
import json
import subprocess
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg

from music_core import (
    Cancelled, Track, download_track, duration_text, fetch_audio, friendly_error,
    load_settings, safe_filename, save_settings, search_target, search_tracks,
    unique_destination,
)


class CoreTests(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(safe_filename(' A/B:C?*<>|" '), "A_B_C______")
        self.assertEqual(safe_filename("..."), "Track")
        self.assertEqual(safe_filename("CON"), "_CON")
        self.assertEqual(safe_filename("nul.mp3"), "_nul.mp3")
        self.assertLessEqual(len(safe_filename("a" * 300)), 120)
        self.assertEqual(safe_filename("Привет мир", True), "Privet mir")

    def test_duration(self):
        self.assertEqual(duration_text(None), "—")
        self.assertEqual(duration_text(0), "0:00")
        self.assertEqual(duration_text(185.9), "3:05")
        self.assertEqual(duration_text(3661), "1:01:01")

    def test_search_target(self):
        self.assertEqual(search_target(" Artist Song ", "YouTube"), "ytsearch15:Artist Song")
        self.assertEqual(search_target("Song", "SoundCloud"), "scsearch15:Song")
        self.assertEqual(search_target("https://example.com/song", "YouTube"), "https://example.com/song")
        for invalid in ("", "   ", "file:///secret", "ftp://example.com", "ytsearch9999:music"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                search_target(invalid, "YouTube")

    def test_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            self.assertEqual(load_settings(path)["quality"], "192")
            save_settings({"quality": "320", "folder": "D:/Музыка", "ascii_names": True}, path)
            settings = load_settings(path)
            self.assertEqual(settings["quality"], "320")
            self.assertTrue(settings["ascii_names"])
            self.assertEqual(settings["folder"], "D:/Музыка")
            for invalid in ("{", "[]", json.dumps({"quality": "bad", "ascii_names": "false", "folder": 4})):
                path.write_text(invalid, encoding="utf-8")
                self.assertEqual(load_settings(path)["quality"], "192")
                self.assertFalse(load_settings(path)["ascii_names"])

    def test_existing_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "song.mp3").touch()
            (folder / "song (2).mp3").touch()
            self.assertEqual(unique_destination(folder, "song").name, "song (3).mp3")

    @patch("music_core.yt_dlp.YoutubeDL")
    def test_search_results(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = {
            "_type": "playlist", "entries": [
                {"title": "Song", "url": "https://example.com/a", "duration": 120, "id": "a"},
                {"title": "Duplicate", "url": "https://example.com/a"},
                {"title": "Live", "url": "https://example.com/b", "is_live": True},
                {"title": "Local", "url": "file:///secret"}, None,
            ]
        }
        tracks = search_tracks("song", "YouTube")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Song")
        with self.assertRaises(ValueError):
            search_tracks("https://example.com/playlist", "YouTube")

    def test_friendly_errors(self):
        self.assertIn("Deno", friendly_error(RuntimeError("HTTP 403")))
        self.assertIn("интернет", friendly_error(RuntimeError("Connection timed out")))

    def test_cancel_before_download(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            download_track(Track("Test", "Artist", 1, "https://example.com", "1"),
                           Path("unused"), "192", False, cancel, lambda *_: None)


class ConversionTests(unittest.TestCase):
    def test_cancel_during_extraction_terminates_worker(self):
        import time

        class SlowHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(2)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"test")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cancel = threading.Event()
        timer = threading.Timer(0.6, cancel.set)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                timer.start()
                started = time.monotonic()
                with self.assertRaises(Cancelled):
                    fetch_audio(f"http://127.0.0.1:{server.server_port}/test.wav", Path(temporary),
                                imageio_ffmpeg.get_ffmpeg_exe(), cancel, lambda *_: None)
                self.assertLess(time.monotonic() - started, 5)
        finally:
            timer.cancel()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_end_to_end_local_http_audio(self):
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with wave.open(str(root / "test.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(22050)
                audio.writeframes(b"\0\0" * 22050)
            handler = functools.partial(QuietHandler, directory=str(root))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/test.wav"
                tracks = search_tracks(url, "YouTube")
                self.assertEqual(len(tracks), 1)
                result = download_track(tracks[0], root / "output", "192", False,
                                        threading.Event(), lambda *_: None)
                self.assertEqual(result.suffix, ".mp3")
                self.assertEqual(result.read_bytes()[:4], b"ID3\x03")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    @patch("music_core.fetch_audio")
    def test_real_mp3_conversion_and_no_overwrite(self, mock_fetch):
        """Use a locally generated WAV instead of downloading copyrighted material."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(22050)
                audio.writeframes(b"\0\0" * 22050)
            mock_fetch.return_value = (source, {"title": "Тест", "artist": "Автор"})
            folder = root / "output"
            folder.mkdir()
            (folder / "Test.mp3").write_bytes(b"existing file")
            progress = []
            result = download_track(Track("Тест", "Автор", 1, "https://example.com", "1"),
                                    folder, "192", True, threading.Event(),
                                    lambda fraction, detail: progress.append(fraction))
            self.assertEqual(result.name, "Test (2).mp3")
            self.assertEqual((folder / "Test.mp3").read_bytes(), b"existing file")
            self.assertGreater(result.stat().st_size, 20000)
            self.assertEqual(result.read_bytes()[:4], b"ID3\x03")
            probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(result)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertIn("44100 Hz", probe.stderr)
            self.assertIn("stereo", probe.stderr)
            self.assertIn("192 kb/s", probe.stderr)
            self.assertEqual(progress[-1], 1)

    @patch("music_core.fetch_audio")
    def test_cancel_during_final_copy_leaves_no_partial_mp3(self, mock_fetch):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(22050)
                audio.writeframes(b"\0\0" * 22050)
            mock_fetch.return_value = (source, {"title": "Test"})
            cancel = threading.Event()
            def report(fraction, _):
                if fraction >= 0.96:
                    cancel.set()
            folder = root / "output"
            with self.assertRaises(Cancelled):
                download_track(Track("Test", "Artist", 1, "https://example.com", "1"),
                               folder, "192", False, cancel, report)
            self.assertEqual(list(folder.glob("*.mp3")), [])


if __name__ == "__main__":
    unittest.main()
