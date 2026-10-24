import os
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import MusicDownloader
from music_core import Track


class WindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = MusicDownloader()
        except tk.TclError as error:
            self.skipTest(f"GUI is unavailable: {error}")
        self.app.withdraw()

    def tearDown(self):
        if hasattr(self, "app"):
            for callback in self.app.tk.call("after", "info"):
                self.app.tk.call("after", "cancel", callback)
            self.app.destroy()

    def test_clipboard_paste_and_replace_selection(self):
        entry = self.app.search_entry
        self.app.clipboard_clear()
        self.app.clipboard_append("Исполнитель — Название песни")
        entry.clipboard_action("paste")
        self.assertEqual(self.app.query.get(), "Исполнитель — Название песни")
        entry.clipboard_action("select_all")
        self.app.clipboard_clear()
        self.app.clipboard_append("Другая песня")
        entry.clipboard_action("paste")
        self.assertEqual(self.app.query.get(), "Другая песня")

    @unittest.skipUnless(os.name == "nt", "Windows key codes")
    def test_russian_layout_shortcuts(self):
        entry = self.app.search_entry
        self.app.clipboard_clear()
        self.app.clipboard_append("Песня")
        event = SimpleNamespace(keycode=86, keysym="Cyrillic_em")
        self.assertEqual(entry._control_key(event), "break")
        self.assertEqual(entry.get(), "Песня")
        entry._control_key(SimpleNamespace(keycode=65, keysym="Cyrillic_ef"))
        entry._control_key(SimpleNamespace(keycode=67, keysym="Cyrillic_es"))
        self.assertEqual(self.app.clipboard_get(), "Песня")
        entry._control_key(SimpleNamespace(keycode=88, keysym="Cyrillic_che"))
        self.assertEqual(entry.get(), "")

    @unittest.skipUnless(os.name == "nt", "Windows key codes")
    def test_ctrl_v_binding_pastes_once(self):
        self.app.deiconify()
        self.app.update()
        self.app.search_entry.focus_force()
        self.app.clipboard_clear()
        self.app.clipboard_append("Тест вставки")
        self.app.search_entry._entry.event_generate("<Control-KeyPress>", keycode=86, state=4)
        self.app.update()
        self.assertEqual(self.app.query.get(), "Тест вставки")

    def test_context_menu_pastes_into_folder(self):
        entry = self.app.folder_entry
        entry.clipboard_action("select_all")
        self.app.clipboard_clear()
        self.app.clipboard_append("D:\\Музыка")
        entry.clipboard_menu.invoke(2)
        self.assertEqual(self.app.folder.get(), "D:\\Музыка")

    def test_paste_does_not_change_disabled_entry(self):
        self.app.query.set("Original")
        self.app.clipboard_clear()
        self.app.clipboard_append("Replacement")
        self.app.search_entry.configure(state="disabled")
        self.app.search_entry.clipboard_action("paste")
        self.assertEqual(self.app.query.get(), "Original")

    def test_selection_and_busy_state(self):
        self.app._show_tracks([
            Track("Первый трек", "Исполнитель", 180, "https://example.com/a", "a"),
            Track("Второй трек", "Исполнитель", 200, "https://example.com/b", "b"),
        ])
        self.assertEqual(self.app.download_button.cget("state"), "disabled")
        self.app._select_all()
        self.assertTrue(all(var.get() for var in self.app.selection))
        self.assertEqual(self.app.download_button.cget("state"), "normal")
        self.app._set_busy(True, downloading=True)
        self.assertEqual(self.app.download_button.cget("state"), "disabled")
        self.assertEqual(self.app.cancel_button.cget("state"), "normal")
        self.app._set_busy(False)
        self.app._select_all()
        self.assertFalse(any(var.get() for var in self.app.selection))

    def test_basket_preserves_choices_across_searches(self):
        first = Track("First", "Artist", 180, "https://example.com/a", "a")
        second = Track("Second", "Artist", 180, "https://example.com/b", "b")
        self.app._show_tracks([first])
        self.app.track_boxes[0].toggle()
        self.assertEqual(list(self.app.basket), [first.url])
        self.assertEqual(self.app.track_rows[0].cget("border_width"), 1)
        self.app._show_tracks([second])
        self.assertFalse(self.app.selection[0].get())
        self.assertIn(first.url, self.app.basket)
        self.app.track_boxes[0].toggle()
        self.assertEqual(list(self.app.basket.values()), [first, second])
        self.app._show_tracks([])
        self.assertEqual(len(self.app.basket), 2)
        self.assertEqual(self.app.download_button.cget("state"), "normal")
        self.app._show_tracks([first])
        self.assertTrue(self.app.selection[0].get())
        self.assertEqual(len(self.app.basket), 2)
        self.app.track_boxes[0].toggle()
        self.assertEqual(list(self.app.basket.values()), [second])

    def test_remove_and_clear_basket_sync_results(self):
        tracks = [Track("A", "Artist", 1, "https://example.com/a", "a"),
                  Track("B", "Artist", 1, "https://example.com/b", "b")]
        self.app._show_tracks(tracks)
        self.app._select_all()
        self.app.basket_buttons[0].invoke()
        self.assertFalse(self.app.selection[0].get())
        self.assertTrue(self.app.selection[1].get())
        self.app._clear_basket()
        self.assertFalse(self.app.basket)
        self.assertFalse(any(var.get() for var in self.app.selection))
        self.assertEqual(self.app.download_button.cget("state"), "disabled")

    def test_select_all_only_affects_current_search(self):
        first = Track("A", "Artist", 1, "https://example.com/a", "a")
        second = Track("B", "Artist", 1, "https://example.com/b", "b")
        self.app._show_tracks([first])
        self.app._select_all()
        self.app._show_tracks([second])
        self.app._select_all()
        self.app._select_all()
        self.assertEqual(list(self.app.basket.values()), [first])
        self.app._set_busy(True, downloading=True)
        self.app._clear_basket()
        self.app._remove_from_basket(first.url)
        self.assertIn(first.url, self.app.basket)

    def test_downloaded_event_removes_only_successful_tracks(self):
        first = Track("A", "Artist", 1, "https://example.com/a", "a")
        second = Track("B", "Artist", 1, "https://example.com/b", "b")
        self.app._show_tracks([first, second])
        self.app._select_all()
        self.app._set_busy(True, downloading=True)
        self.app.events.put(("downloaded", first.url))
        self.app.events.put(("finished", (1, 0, True)))
        self.app._poll()
        self.assertEqual(list(self.app.basket.values()), [second])
        self.assertFalse(self.app.selection[0].get())
        self.assertTrue(self.app.selection[1].get())
        self.assertEqual(self.app.download_button.cget("state"), "normal")

    @patch("main.download_track")
    def test_batch_download_uses_tracks_from_multiple_searches(self, mock_download):
        first = Track("A", "Artist", 1, "https://example.com/a", "a")
        second = Track("B", "Artist", 1, "https://example.com/b", "b")
        self.app._show_tracks([first])
        self.app._select_all()
        self.app._show_tracks([second])
        self.app._select_all()
        real_thread = threading.Thread
        workers = []

        def start_worker(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            workers.append(thread)
            return thread

        with tempfile.TemporaryDirectory() as temporary, patch("main.threading.Thread", side_effect=start_worker), patch.object(self.app, "_save"):
            self.app.folder.set(temporary)
            mock_download.return_value = Path(temporary) / "test.mp3"
            self.app._download()
            workers[0].join(timeout=5)
            self.assertFalse(workers[0].is_alive())
            self.app._poll()
        self.assertEqual([call.args[0] for call in mock_download.call_args_list], [first, second])
        self.assertFalse(self.app.basket)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.download_button.cget("state"), "disabled")

    def test_worker_events_update_ui(self):
        self.app._set_busy(True)
        self.app.events.put(("results", [Track("Test", "Artist", 1, "https://example.com", "a")]))
        self.app._poll()
        self.assertFalse(self.app.busy)
        self.assertEqual(len(self.app.tracks), 1)
        self.app._set_busy(True, downloading=True)
        self.app.events.put(("progress", (0.5, "Test progress")))
        self.app.events.put(("finished", (1, 0, False)))
        self.app._poll()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.progress.get(), 1)

    @patch("main.messagebox.askyesno", return_value=False)
    def test_close_can_be_declined_during_download(self, _):
        self.app._set_busy(True, downloading=True)
        self.app._close()
        self.assertFalse(self.app.closing)
        self.assertFalse(self.app.cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
