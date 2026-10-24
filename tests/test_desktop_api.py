import sys
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from desktop_api import DesktopAPI
from music_core import Cancelled, Track


class DesktopAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parent / "desktop-api-test-output"
        self.settings = {
            "folder": str(self.folder), "quality": "192",
            "ascii_names": False, "source": "YouTube",
        }
        self.gates = []
        self.close_finished = None
        self.load = self.start_patch("desktop_api.load_settings", return_value=self.settings.copy())
        self.save = self.start_patch("desktop_api.save_settings")
        self.search_tracks = self.start_patch("desktop_api.search_tracks", return_value=[])
        self.download_track = self.start_patch("desktop_api.download_track")
        self.webview = SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=object()))
        webview_patch = patch.dict(sys.modules, {"webview": self.webview})
        webview_patch.start()
        self.addCleanup(webview_patch.stop)
        self.api = DesktopAPI()
        self.addCleanup(self.finish_workers)
        self.a = self.track("a")
        self.b = self.track("b")
        self.c = self.track("c")

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    @staticmethod
    def track(identifier, title=None):
        return Track(title or "Song " + identifier, "Artist", 123,
                     "https://example.test/" + identifier, identifier)

    def gate(self):
        event = threading.Event()
        self.gates.append(event)
        return event

    @staticmethod
    def wait_for(event):
        if not event.wait(5):
            raise RuntimeError("Test worker was not released within five seconds")

    def join_worker(self):
        # Workers acquire this lock before finishing; never join while holding it.
        with self.api._lock:
            worker = self.api._worker
        self.assertIsNotNone(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive(), "DesktopAPI worker did not finish")

    def finish_workers(self):
        self.api._cancel.set()
        for gate in self.gates:
            gate.set()
        with self.api._lock:
            worker = self.api._worker
        if worker is not None:
            worker.join(5)
            self.assertFalse(worker.is_alive(), "Worker leaked from test")
        if self.close_finished is not None:
            self.assertTrue(self.close_finished.wait(5), "Close worker did not finish")

    def search(self, tracks, query="songs", source="YouTube"):
        self.search_tracks.return_value = tracks
        self.assertEqual(self.api.search(query, source), {"ok": True})
        self.join_worker()
        self.assertEqual(self.api.get_state()["busy"], "idle")

    def basket_urls(self):
        return [track["url"] for track in self.api.get_state()["basket"]]

    def seed_basket(self, tracks=None):
        self.search([self.a, self.b] if tracks is None else tracks)
        self.assertEqual(self.api.select_all(True), {"ok": True})

    def hold_operation(self, operation):
        entered, release = self.gate(), self.gate()
        if operation == "search":
            def search(query, source):
                entered.set()
                self.wait_for(release)
                return [self.c]
            self.search_tracks.side_effect = search
            self.assertTrue(self.api.search("next", "SoundCloud")["ok"])
        else:
            def download(track, folder, quality, ascii_names, cancel, report):
                entered.set()
                self.wait_for(release)
                if cancel.is_set():
                    raise Cancelled()
                return folder / (track.identifier + ".mp3")
            self.download_track.side_effect = download
            self.assertTrue(self.api.start_download()["ok"])
        self.assertTrue(entered.wait(5), "Operation did not start")
        return release

    def test_search_still_works_when_settings_cannot_be_saved(self):
        self.save.side_effect = PermissionError("read only")
        self.search_tracks.return_value = [self.a]
        self.assertTrue(self.api.search("query", "YouTube")["ok"])
        self.join_worker()
        state = self.api.get_state()
        self.assertEqual(state["results"], [asdict(self.a)])
        self.assertTrue(any(log["level"] == "error" for log in state["logs"]))

    def test_download_rejects_persisted_relative_folder(self):
        self.seed_basket()
        self.api._settings["folder"] = "relative"
        self.assertFalse(self.api.start_download()["ok"])
        self.assertEqual(self.api.get_state()["busy"], "idle")
        self.download_track.assert_not_called()

    def test_download_expands_persisted_home_folder(self):
        self.seed_basket([self.a])
        self.api._settings["folder"] = "~/Music/MusicDownloader"
        self.download_track.return_value = Path.home() / "Music" / "test.mp3"
        self.assertTrue(self.api.start_download()["ok"])
        self.join_worker()
        self.assertEqual(self.download_track.call_args.args[1], Path.home() / "Music" / "MusicDownloader")

    def test_initial_state_uses_mock_settings_without_writing(self):
        state = self.api.get_state()
        self.load.assert_called_once_with()
        self.save.assert_not_called()
        self.assertEqual(state["settings"], self.settings)
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["busy"], "idle")
        self.assertEqual(state["results"], [])
        self.assertEqual(state["basket"], [])
        self.assertEqual(state["logs"], [])
        self.assertEqual(state["progress"], 0)
        self.assertIsNone(state["current_track"])
        self.assertIsNone(state["summary"])
        self.assertFalse(state["closing"])

    def test_basket_survives_search_workers_and_deduplicates_by_url(self):
        self.search([self.a, self.b], "  first  ")
        self.search_tracks.assert_called_once_with("first", "YouTube")
        self.assertTrue(self.api.set_selected(self.a.url, True)["ok"])
        self.assertTrue(self.api.set_selected(self.a.url, True)["ok"])
        renamed_a = self.track("a", "Different metadata")
        self.search([renamed_a, self.c, self.c], "second", "SoundCloud")
        state = self.api.get_state()
        self.assertEqual(state["query"], "second")
        self.assertEqual(state["settings"]["source"], "SoundCloud")
        self.assertEqual(state["results"], [asdict(renamed_a), asdict(self.c), asdict(self.c)])
        self.assertEqual(state["basket"], [asdict(self.a)])
        self.assertTrue(self.api.select_all(True)["ok"])
        self.assertEqual(self.basket_urls(), [self.a.url, self.c.url])
        self.assertEqual(self.api.get_state()["basket"][0], asdict(self.a))
        self.search([], "empty")
        self.assertEqual(self.api.get_state()["results"], [])
        self.assertEqual(self.basket_urls(), [self.a.url, self.c.url])

    def test_select_all_and_deselect_all_only_affect_current_results(self):
        self.seed_basket()
        self.search([self.b, self.c], "second")
        self.assertTrue(self.api.select_all(True)["ok"])
        self.assertEqual(self.basket_urls(), [self.a.url, self.b.url, self.c.url])
        self.assertTrue(self.api.select_all(False)["ok"])
        self.assertEqual(self.basket_urls(), [self.a.url])
        self.search([], "empty")
        self.assertTrue(self.api.select_all(False)["ok"])
        self.assertEqual(self.basket_urls(), [self.a.url])

    def test_remove_old_result_and_clear_basket(self):
        self.seed_basket()
        self.search([self.c], "second")
        self.assertTrue(self.api.remove_track(self.a.url)["ok"])
        self.assertEqual(self.basket_urls(), [self.b.url])
        self.assertTrue(self.api.remove_track("unknown")["ok"])
        self.assertTrue(self.api.clear_basket()["ok"])
        self.assertEqual(self.basket_urls(), [])
        self.assertEqual(self.api.get_state()["results"], [asdict(self.c)])
        self.assertTrue(self.api.clear_basket()["ok"])

    def test_invalid_selection_does_not_change_basket(self):
        self.seed_basket()
        for url, selected in ((None, True), (123, False), (self.a.url, 1),
                              (self.a.url, "true"), ("unknown", True)):
            with self.subTest(url=url, selected=selected):
                self.assertFalse(self.api.set_selected(url, selected)["ok"])
                self.assertEqual(self.basket_urls(), [self.a.url, self.b.url])
        for selected in (None, 1, "false", []):
            with self.subTest(selected=selected):
                self.assertFalse(self.api.select_all(selected)["ok"])
                self.assertEqual(self.basket_urls(), [self.a.url, self.b.url])

    def test_invalid_search_does_not_start_worker_or_save(self):
        for query in (None, 12, [], "", "   "):
            with self.subTest(query=query):
                self.assertFalse(self.api.search(query, "YouTube")["ok"])
        self.assertFalse(self.api.search("song", "invalid source")["ok"])
        self.search_tracks.assert_not_called()
        self.save.assert_not_called()
        self.assertIsNone(self.api._worker)
        self.assertEqual(self.api.get_state()["busy"], "idle")

    def test_search_failure_keeps_basket_and_returns_to_idle(self):
        self.seed_basket()
        self.search_tracks.side_effect = RuntimeError("search exploded")
        self.assertTrue(self.api.search("second", "YouTube")["ok"])
        self.join_worker()
        state = self.api.get_state()
        self.assertEqual(state["busy"], "idle")
        self.assertEqual(self.basket_urls(), [self.a.url, self.b.url])
        self.assertTrue(any(log["level"] == "error" and "search exploded" in log["text"]
                            for log in state["logs"]))

    def test_mutating_operations_are_blocked_while_busy(self):
        for operation in ("search", "download"):
            with self.subTest(operation=operation):
                self.seed_basket()
                release = self.hold_operation(operation)
                before = self.api.get_state()
                save_count = self.save.call_count
                self.api._window = Mock()
                actions = (
                    lambda: self.api.search("blocked", "YouTube"),
                    lambda: self.api.set_selected(self.a.url, False),
                    lambda: self.api.select_all(False),
                    lambda: self.api.remove_track(self.a.url),
                    self.api.clear_basket,
                    lambda: self.api.update_settings({"quality": "320"}),
                    self.api.choose_folder,
                    self.api.start_download,
                )
                for action in actions:
                    self.assertFalse(action()["ok"])
                self.assertEqual(self.api.get_state(), before)
                self.assertEqual(self.save.call_count, save_count)
                self.api._window.create_file_dialog.assert_not_called()
                release.set()
                self.join_worker()
                self.search_tracks.side_effect = None

    def test_valid_settings_are_normalized_and_persisted(self):
        destination = self.folder / "new"
        patch_values = {"folder": "  " + str(destination) + "  ", "quality": "320",
                        "ascii_names": True, "source": "SoundCloud"}
        revision = self.api.get_state()["revision"]
        self.assertTrue(self.api.update_settings(patch_values)["ok"])
        expected = dict(patch_values, folder=str(destination))
        self.save.assert_called_once_with(expected)
        self.assertEqual(self.api.get_state()["settings"], expected)
        self.assertGreater(self.api.get_state()["revision"], revision)

    def test_invalid_settings_patch_is_atomic(self):
        invalid_patches = (
            None, [], "settings", {"quality": 320}, {"quality": "999"},
            {"source": "Spotify"}, {"ascii_names": 1}, {"folder": ""},
            {"folder": "  "}, {"folder": "relative/music"}, {"folder": None},
            {"unknown": True}, {"quality": "320", "ascii_names": "yes"},
            {"quality": "320", "folder": "relative"},
        )
        for invalid in invalid_patches:
            with self.subTest(patch=invalid):
                self.assertFalse(self.api.update_settings(invalid)["ok"])
                self.assertEqual(self.api.get_state()["settings"], self.settings)
                self.save.assert_not_called()

    def test_settings_save_failure_does_not_commit_partial_settings(self):
        self.save.side_effect = OSError("settings are read only")
        self.assertFalse(self.api.update_settings({"quality": "320"})["ok"])
        self.assertEqual(self.api.get_state()["settings"], self.settings)
        self.assertTrue(self.api.search("song", "SoundCloud")["ok"])
        self.join_worker()
        self.assertEqual(self.api.get_state()["settings"]["source"], "SoundCloud")
        self.assertEqual(self.api.get_state()["settings"]["quality"], "192")
        self.assertEqual(self.api.get_state()["busy"], "idle")
        self.search_tracks.assert_called_once_with("song", "SoundCloud")

    def test_choose_folder_requires_window(self):
        self.assertFalse(self.api.choose_folder()["ok"])
        self.save.assert_not_called()

    def test_choose_folder_uses_webview_dialog_and_saves_selection(self):
        chosen = str(self.folder / "selected")
        self.api._window = Mock()
        self.api._window.create_file_dialog.return_value = (chosen,)
        with patch("desktop_api.Path.is_dir", return_value=True):
            result = self.api.choose_folder()
        self.assertEqual(result, {"ok": True, "folder": chosen})
        self.api._window.create_file_dialog.assert_called_once_with(
            self.webview.FileDialog.FOLDER, directory=str(self.folder))
        self.assertEqual(self.api.get_state()["settings"]["folder"], chosen)
        self.save.assert_called_once_with(dict(self.settings, folder=chosen))

    def test_choose_folder_cancel_uses_home_fallback_without_saving(self):
        self.api._window = Mock()
        self.api._window.create_file_dialog.return_value = None
        before = self.api.get_state()
        with patch("desktop_api.Path.is_dir", return_value=False):
            self.assertEqual(self.api.choose_folder(), {"ok": True, "folder": None})
        self.api._window.create_file_dialog.assert_called_once_with(
            self.webview.FileDialog.FOLDER, directory=str(Path.home()))
        self.assertEqual(self.api.get_state(), before)
        self.save.assert_not_called()

    def test_choose_folder_errors_are_reported_without_saving(self):
        self.api._window = Mock()
        self.api._window.create_file_dialog.side_effect = RuntimeError("dialog failed")
        self.assertFalse(self.api.choose_folder()["ok"])
        self.assertEqual(self.api.get_state()["settings"], self.settings)
        self.save.assert_not_called()
        self.assertEqual(self.api.get_state()["logs"][-1]["level"], "error")

    def test_choose_folder_invalid_selection_does_not_commit(self):
        self.api._window = Mock()
        self.api._window.create_file_dialog.return_value = ("relative/path",)
        self.assertFalse(self.api.choose_folder()["ok"])
        self.assertEqual(self.api.get_state()["settings"], self.settings)
        self.save.assert_not_called()

    def test_open_nonexistent_folder_does_not_launch_anything(self):
        with patch("desktop_api.Path.is_dir", return_value=False), \
                patch("desktop_api.os.startfile", create=True) as startfile, \
                patch("desktop_api.subprocess.Popen") as popen:
            self.assertFalse(self.api.open_folder()["ok"])
        startfile.assert_not_called()
        popen.assert_not_called()
        self.save.assert_not_called()

    def test_empty_download_and_idle_cancel_are_rejected(self):
        self.assertFalse(self.api.start_download()["ok"])
        self.assertFalse(self.api.cancel_download()["ok"])
        self.assertEqual(self.api.get_state()["busy"], "idle")
        self.assertIsNone(self.api._worker)
        self.download_track.assert_not_called()

    def test_batch_downloads_entire_cross_search_basket_and_keeps_failures(self):
        self.seed_basket()
        self.search([self.c], "second", "SoundCloud")
        self.assertTrue(self.api.select_all(True)["ok"])
        calls = []

        def download(track, folder, quality, ascii_names, cancel, report):
            calls.append((track, folder, quality, ascii_names, cancel))
            report(0.5, "Downloading")
            if track.url == self.b.url:
                raise RuntimeError("track failed")
            return folder / (track.identifier + ".mp3")

        self.download_track.side_effect = download
        self.assertTrue(self.api.start_download()["ok"])
        self.join_worker()
        self.assertEqual([call[0] for call in calls], [self.a, self.b, self.c])
        for track, folder, quality, ascii_names, cancel in calls:
            self.assertEqual(folder, self.folder)
            self.assertEqual(quality, "192")
            self.assertFalse(ascii_names)
            self.assertIs(cancel, self.api._cancel)
        state = self.api.get_state()
        self.assertEqual(state["summary"], {"saved": 2, "failed": 1})
        self.assertEqual(state["busy"], "idle")
        self.assertEqual(state["progress"], 1)
        self.assertIsNone(state["current_track"])
        self.assertEqual(self.basket_urls(), [self.b.url])
        self.assertEqual(state["results"], [asdict(self.c)])
        self.assertTrue(any(log["level"] == "error" and "track failed" in log["text"]
                            for log in state["logs"]))
        self.download_track.side_effect = lambda track, folder, *args: folder / "retry.mp3"
        self.assertTrue(self.api.start_download()["ok"])
        self.join_worker()
        self.assertEqual(self.api.get_state()["summary"], {"saved": 1, "failed": 0})
        self.assertEqual(self.basket_urls(), [])

    def test_cancel_preserves_unfinished_tracks_and_partial_progress_then_can_retry(self):
        self.seed_basket([self.a, self.b, self.c])
        entered, release = self.gate(), self.gate()

        def download(track, folder, quality, ascii_names, cancel, report):
            if track == self.a:
                return folder / "a.mp3"
            report(0.5, "Halfway")
            entered.set()
            self.wait_for(release)
            report(0.5, "Late progress")
            raise Cancelled()

        self.download_track.side_effect = download
        self.assertTrue(self.api.start_download()["ok"])
        self.assertTrue(entered.wait(5))
        active = self.api.get_state()
        self.assertEqual(active["current_track"], asdict(self.b))
        self.assertAlmostEqual(active["progress"], 0.5)
        self.assertTrue(self.api.cancel_download()["ok"])
        stopping = self.api.get_state()
        self.assertTrue(self.api._cancel.is_set())
        self.assertEqual(stopping["busy"], "download")
        self.assertNotEqual(stopping["status"], active["status"])
        release.set()
        self.join_worker()
        state = self.api.get_state()
        self.assertEqual(state["summary"], {"saved": 1, "failed": 0})
        self.assertEqual(state["busy"], "idle")
        self.assertIsNone(state["current_track"])
        self.assertAlmostEqual(state["progress"], 0.5)
        self.assertEqual(self.basket_urls(), [self.b.url, self.c.url])
        self.assertEqual(self.download_track.call_count, 2)
        self.assertFalse(any(log["level"] == "error" for log in state["logs"]))
        self.download_track.side_effect = lambda track, folder, *args: folder / "retry.mp3"
        self.assertTrue(self.api.start_download()["ok"])
        self.join_worker()
        self.assertFalse(self.api._cancel.is_set())
        self.assertEqual(self.api.get_state()["summary"], {"saved": 2, "failed": 0})
        self.assertEqual(self.basket_urls(), [])

    def test_progress_is_clamped_and_reports_increment_revision(self):
        self.seed_basket([self.a])
        snapshots = []

        def download(track, folder, quality, ascii_names, cancel, report):
            for fraction in (-2, 0.25, 5):
                report(fraction, "progress")
                snapshots.append(self.api.get_state())
            return folder / "a.mp3"

        self.download_track.side_effect = download
        self.assertTrue(self.api.start_download()["ok"])
        self.join_worker()
        self.assertEqual([state["progress"] for state in snapshots], [0, 0.25, 1])
        self.assertTrue(all(state["current_track"] == asdict(self.a) for state in snapshots))
        self.assertLess(snapshots[0]["revision"], snapshots[1]["revision"])
        self.assertLess(snapshots[1]["revision"], snapshots[2]["revision"])

    def test_state_snapshots_are_detached_including_nested_objects(self):
        self.seed_basket([self.a])
        release = self.hold_operation("download")
        original = self.api.get_state()
        snapshot = self.api.get_state()
        snapshot["settings"]["quality"] = "corrupted"
        snapshot["results"][0]["title"] = "corrupted"
        snapshot["basket"][0]["artist"] = "corrupted"
        snapshot["current_track"]["url"] = "corrupted"
        snapshot["logs"][0]["text"] = "corrupted"
        snapshot["logs"].append({"text": "extra"})
        snapshot["revision"] = -1
        self.assertEqual(self.api.get_state(), original)
        self.assertEqual(self.api.get_state()["revision"], original["revision"])
        release.set()
        self.join_worker()
        completed = self.api.get_state()
        self.assertGreater(completed["revision"], original["revision"])
        self.assertEqual(original["busy"], "download")
        self.assertIsNone(original["summary"])
        completed["summary"]["saved"] = 999
        self.assertEqual(self.api.get_state()["summary"], {"saved": 1, "failed": 0})

    def test_close_idle_preserves_basket_and_blocks_further_mutations(self):
        self.seed_basket()
        self.api._window = Mock()
        before = self.api.get_state()
        self.assertTrue(self.api._on_closing())
        self.assertTrue(self.api.get_state()["closing"])
        self.assertGreater(self.api.get_state()["revision"], before["revision"])
        self.assertEqual(self.basket_urls(), [self.a.url, self.b.url])
        self.assertFalse(self.api._on_closing())
        self.assertFalse(self.api.clear_basket()["ok"])
        self.assertFalse(self.api.search("new", "YouTube")["ok"])
        self.assertFalse(self.api.start_download()["ok"])
        self.assertFalse(self.api.update_settings({"quality": "320"})["ok"])
        self.api._window.create_confirmation_dialog.assert_not_called()
        self.api._window.destroy.assert_not_called()

    def test_declining_close_leaves_download_running(self):
        self.seed_basket()
        release = self.hold_operation("download")
        self.api._window = Mock()
        self.api._window.create_confirmation_dialog.return_value = False
        before = self.api.get_state()
        self.assertFalse(self.api._on_closing())
        self.assertEqual(self.api.get_state(), before)
        self.assertFalse(self.api._cancel.is_set())
        self.api._window.create_confirmation_dialog.assert_called_once()
        self.api._window.destroy.assert_not_called()
        release.set()
        self.join_worker()
        self.assertEqual(self.api.get_state()["summary"], {"saved": 2, "failed": 0})

    def test_confirming_close_cancels_joins_then_destroys_mock_window(self):
        self.seed_basket()
        release = self.hold_operation("download")
        window = MagicMock()
        window.create_confirmation_dialog.return_value = True
        window.events.closing.__isub__.return_value = window.events.closing
        destroyed = threading.Event()
        self.close_finished = destroyed
        window.destroy.side_effect = destroyed.set
        self.api._window = window
        self.assertFalse(self.api._on_closing())
        state = self.api.get_state()
        self.assertTrue(state["closing"])
        self.assertEqual(state["busy"], "download")
        self.assertTrue(self.api._cancel.is_set())
        window.destroy.assert_not_called()
        self.assertFalse(self.api._on_closing())
        window.create_confirmation_dialog.assert_called_once()
        release.set()
        self.join_worker()
        self.assertTrue(destroyed.wait(5))
        window.events.closing.__isub__.assert_called_once_with(self.api._on_closing)
        window.destroy.assert_called_once_with()
        state = self.api.get_state()
        self.assertEqual(state["busy"], "idle")
        self.assertTrue(state["closing"])
        self.assertEqual(state["summary"], {"saved": 0, "failed": 0})
        self.assertEqual(self.basket_urls(), [self.a.url, self.b.url])


if __name__ == "__main__":
    unittest.main()
