import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import runtime_ffmpeg
from desktop_api import DesktopAPI
from music_core import Cancelled, Track, safe_filename


class FrozenEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "MusicDownloader" / "tools"
        self.start_patch("runtime_ffmpeg.sys.frozen", True, create=True)
        environment = patch.dict(os.environ, {
            "LOCALAPPDATA": str(self.root), "IMAGEIO_FFMPEG_EXE": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.urlopen = self.start_patch(
            "runtime_ffmpeg.urllib.request.urlopen",
            side_effect=AssertionError("Unexpected network access"),
        )

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def give_consent(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "download-consent").touch()


class RuntimeFFmpegTests(FrozenEnvironmentTests):
    def setUp(self):
        super().setUp()
        self.executable = b"MZ simulated pinned FFmpeg executable"
        self.filename = "ffmpeg-test.exe"
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w") as package:
            package.writestr("imageio_ffmpeg/binaries/" + self.filename, self.executable)
            package.writestr("imageio_ffmpeg/__init__.py", b"not extracted")
        self.wheel = wheel.getvalue()
        self.manifest = {
            "url": "https://files.pythonhosted.org/packages/test/imageio_ffmpeg-pinned.whl",
            "filename": self.filename,
            "wheel_sha256": hashlib.sha256(self.wheel).hexdigest(),
            "exe_sha256": hashlib.sha256(self.executable).hexdigest(),
        }
        self.read_manifest = self.start_patch(
            "runtime_ffmpeg.Path.read_text", return_value=json.dumps(self.manifest),
        )
        self.target = self.cache / self.filename

    def serve_wheel(self, data=None):
        response = io.BytesIO(self.wheel if data is None else data)
        self.urlopen.side_effect = None
        self.urlopen.return_value = response
        return response

    def assert_not_installed(self):
        self.assertFalse(self.target.exists())
        self.assertFalse((self.cache / (self.filename + ".tmp")).exists())

    def test_environment_override_uses_existing_file_without_consent(self):
        executable = self.root / "custom-ffmpeg.exe"
        executable.write_bytes(b"custom executable")
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": str(executable)}):
            self.assertEqual(runtime_ffmpeg.get_ffmpeg(), str(executable))
        self.urlopen.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_missing_environment_override_falls_back_to_valid_cache(self):
        self.cache.mkdir(parents=True)
        self.target.write_bytes(self.executable)
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": str(self.root / "missing.exe")}):
            self.assertEqual(runtime_ffmpeg.get_ffmpeg(), str(self.target))
        self.urlopen.assert_not_called()

    def test_valid_cache_skips_download_and_does_not_require_consent(self):
        self.cache.mkdir(parents=True)
        self.target.write_bytes(self.executable)
        progress = Mock()
        self.assertEqual(runtime_ffmpeg.get_ffmpeg(progress=progress), str(self.target))
        self.assertEqual(self.target.read_bytes(), self.executable)
        self.urlopen.assert_not_called()
        progress.assert_not_called()
        self.assertFalse((self.cache / "download-consent").exists())

    def test_missing_consent_rejects_download(self):
        progress = Mock()
        with self.assertRaisesRegex(RuntimeError, "Не подтверждена загрузка FFmpeg"):
            runtime_ffmpeg.get_ffmpeg(progress=progress)
        self.urlopen.assert_not_called()
        progress.assert_not_called()
        self.assert_not_installed()

    def test_invalid_cached_executable_does_not_bypass_consent(self):
        self.cache.mkdir(parents=True)
        self.target.write_bytes(b"corrupt cached executable")
        with self.assertRaisesRegex(RuntimeError, "Не подтверждена загрузка FFmpeg"):
            runtime_ffmpeg.get_ffmpeg()
        self.urlopen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"corrupt cached executable")

    def test_pinned_wheel_download_installs_only_verified_executable(self):
        self.give_consent()
        response = self.serve_wheel()
        progress = Mock()
        self.assertEqual(runtime_ffmpeg.get_ffmpeg(progress=progress), str(self.target))
        self.read_manifest.assert_called_once_with(encoding="utf-8")
        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, self.manifest["url"])
        self.assertEqual(request.get_header("User-agent"), "MusicDrive/1.0")
        self.assertEqual(self.urlopen.call_args.kwargs, {"timeout": 30})
        self.assertTrue(response.closed)
        self.assertEqual(self.target.read_bytes(), self.executable)
        self.assertEqual(
            {path.name for path in self.cache.iterdir()},
            {self.filename, "download-consent"},
        )
        progress.assert_called_once()
        self.assertEqual(progress.call_args.args[0], 0)
        self.assertIn("FFmpeg", progress.call_args.args[1])
        self.urlopen.reset_mock()
        self.assertEqual(runtime_ffmpeg.get_ffmpeg(), str(self.target))
        self.urlopen.assert_not_called()

    def test_invalid_cache_is_replaced_after_verified_download(self):
        self.give_consent()
        self.target.write_bytes(b"corrupt cached executable")
        self.serve_wheel()
        self.assertEqual(runtime_ffmpeg.get_ffmpeg(), str(self.target))
        self.assertEqual(self.target.read_bytes(), self.executable)
        self.urlopen.assert_called_once()

    def test_wheel_hash_mismatch_leaves_no_target(self):
        self.give_consent()
        response = self.serve_wheel(self.wheel + b"tampered")
        with self.assertRaisesRegex(RuntimeError, "Не совпала контрольная сумма FFmpeg"):
            runtime_ffmpeg.get_ffmpeg()
        self.assertTrue(response.closed)
        self.assert_not_installed()

    def test_executable_hash_mismatch_leaves_no_target(self):
        self.give_consent()
        self.manifest["exe_sha256"] = hashlib.sha256(b"different executable").hexdigest()
        self.read_manifest.return_value = json.dumps(self.manifest)
        self.serve_wheel()
        with self.assertRaisesRegex(RuntimeError, "Повреждён исполняемый файл FFmpeg"):
            runtime_ffmpeg.get_ffmpeg()
        self.assert_not_installed()

    def test_failed_verification_preserves_existing_cache(self):
        self.give_consent()
        self.target.write_bytes(b"previous cache")
        self.serve_wheel(b"bad wheel")
        with self.assertRaisesRegex(RuntimeError, "Не совпала контрольная сумма FFmpeg"):
            runtime_ffmpeg.get_ffmpeg()
        self.assertEqual(self.target.read_bytes(), b"previous cache")
        self.assertFalse((self.cache / (self.filename + ".tmp")).exists())

    def test_already_cancelled_download_leaves_no_target(self):
        self.give_consent()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            runtime_ffmpeg.get_ffmpeg(cancel=cancel)
        self.urlopen.assert_not_called()
        self.assert_not_installed()

    def test_cancellation_during_response_read_leaves_no_target(self):
        self.give_consent()
        response = self.serve_wheel()
        cancel = threading.Event()
        read = response.read

        def read_and_cancel(size):
            chunk = read(size)
            cancel.set()
            return chunk

        with patch.object(response, "read", side_effect=read_and_cancel):
            with self.assertRaises(Cancelled):
                runtime_ffmpeg.get_ffmpeg(cancel=cancel)
        self.assertTrue(cancel.is_set())
        self.assertTrue(response.closed)
        self.assert_not_installed()


class TransliterationTests(unittest.TestCase):
    def test_russian_letters_and_case(self):
        for text, expected in (
            ("Привет мир", "Privet mir"),
            ("Ёж Щука Юлия Яна", "Iozh Shchuka Iuliia Iana"),
            ("Съешь ещё этих мягких булок", "Sesh eshchio etikh miagkikh bulok"),
            ("ЖЧШЩ", "ZhChShShch"),
        ):
            with self.subTest(text=text):
                self.assertEqual(runtime_ffmpeg.transliterate(text), expected)

    def test_accents_and_ascii_are_normalized(self):
        for text, expected in (
            ("Beyoncé — Déjà vu", "Beyonce  Deja vu"),
            ("Café naïve Ångström", "Cafe naive Angstrom"),
            ("Cafe\u0301", "Cafe"),
            ("Artist - Song 123!", "Artist - Song 123!"),
            ("", ""),
        ):
            with self.subTest(text=text):
                self.assertEqual(runtime_ffmpeg.transliterate(text), expected)

    def test_ascii_filename_uses_transliteration(self):
        self.assertEqual(safe_filename("Бьорк / Café", True), "Bork _ Cafe")
        self.assertEqual(safe_filename("Бьорк / Café", False), "Бьорк _ Café")


class DesktopFFmpegConsentTests(FrozenEnvironmentTests):
    def setUp(self):
        super().setUp()
        self.settings = {
            "folder": str(self.root / "music"), "quality": "192",
            "ascii_names": False, "source": "YouTube",
        }
        self.start_patch("desktop_api.load_settings", return_value=self.settings.copy())
        self.save_settings = self.start_patch("desktop_api.save_settings")
        self.download_track = self.start_patch("desktop_api.download_track")
        self.thread = self.start_patch("desktop_api.threading.Thread")
        self.api = DesktopAPI()
        track = Track("Song", "Artist", 120, "https://example.test/song", "song")
        self.api._results = [track]
        self.assertTrue(self.api.set_selected(track.url, True)["ok"])

    def assert_consent_rejected(self):
        before = self.api.get_state()
        result = self.api.start_download()
        self.assertFalse(result["ok"])
        self.assertIn("Установка FFmpeg отменена", result["error"])
        self.assertIn("Поиск музыки остаётся доступен", result["error"])
        self.assertEqual(self.api.get_state(), before)
        self.assertIsNone(self.api._worker)
        self.thread.assert_not_called()
        self.download_track.assert_not_called()
        self.save_settings.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse((self.cache / "download-consent").exists())
        self.assertFalse(Path(self.settings["folder"]).exists())

    def test_declining_consent_does_not_start_download_or_write_settings(self):
        self.api._window = Mock()
        self.api._window.create_confirmation_dialog.return_value = False
        self.assert_consent_rejected()
        self.api._window.create_confirmation_dialog.assert_called_once()
        title, message = self.api._window.create_confirmation_dialog.call_args.args
        self.assertIn("FFmpeg", title)
        self.assertIn("PyPI", message)
        self.assertIn("GPLv3+", message)

    def test_missing_window_rejects_download_without_consent(self):
        self.assert_consent_rejected()

    def test_declining_consent_still_allows_search(self):
        self.api._window = Mock()
        self.api._window.create_confirmation_dialog.return_value = False
        self.assert_consent_rejected()
        self.assertEqual(self.api.search("another song", "YouTube"), {"ok": True})
        self.assertEqual(self.api.get_state()["busy"], "search")
        self.thread.assert_called_once()
        self.thread.return_value.start.assert_called_once_with()
        self.download_track.assert_not_called()
        self.urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
