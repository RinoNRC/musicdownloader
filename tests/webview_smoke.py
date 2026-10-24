"""Manual WebView2 integration smoke test; opens a window, no internet or user settings changes.

Run from the project root: .venv\Scripts\python.exe tests\webview_smoke.py
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webview

from desktop_api import DesktopAPI
from music_core import Track


METHODS = ("get_state", "search", "set_selected", "select_all", "remove_track", "clear_basket",
           "update_settings", "choose_folder", "open_folder", "start_download", "cancel_download")


def main():
    success = threading.Event()
    failure = []
    with tempfile.TemporaryDirectory(prefix="musicdrive-ui-test-") as temporary:
        settings = {"folder": temporary, "quality": "192", "ascii_names": False, "source": "YouTube"}
        track = Track("<img src=x onerror='window.injected=true'> Тестовая песня", "Исполнитель", 185,
                      "https://example.test/track", "track")
        with patch("desktop_api.load_settings", return_value=settings), patch("desktop_api.save_settings"), \
                patch("desktop_api.search_tracks", return_value=[track]), \
                patch("desktop_api.download_track", return_value=Path(temporary) / "test.mp3"):
            api = DesktopAPI()
            window = webview.create_window("Music / Drive — integration test",
                                           url=str(Path(__file__).resolve().parents[1] / "web" / "index.html"),
                                           width=1320, height=900)
            window.expose(*(getattr(api, name) for name in METHODS))
            api._window = window

            def evaluate_async(script):
                ready = threading.Event()
                result = []
                window.evaluate_js(script, lambda value: (result.append(value), ready.set()))
                if not ready.wait(10):
                    raise AssertionError("JS promise did not resolve: " + script)
                return result[0]

            def wait_for(script):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if window.evaluate_js(script):
                        return
                    time.sleep(0.1)
                raise AssertionError("DOM condition did not become true: " + script)

            def check():
                try:
                    wait_for("!!window.pywebview?.api?.get_state")
                    window.evaluate_js("window.uiErrors=[];addEventListener('error', e=>uiErrors.push(e.message));addEventListener('unhandledrejection', e=>uiErrors.push(String(e.reason)))")
                    state = evaluate_async("pywebview.api.get_state()")
                    assert state["busy"] == "idle"
                    assert window._js_api is None
                    result = evaluate_async("pywebview.api.search('Тестовая песня', 'YouTube')")
                    assert result["ok"], result
                    api._worker.join(5)
                    assert not api._worker.is_alive()
                    wait_for("document.body.textContent.includes('Тестовая песня')")
                    assert not window.evaluate_js("!!window.injected"), "Remote title executed as HTML"
                    wait_for("document.querySelector('.track-select') && !document.querySelector('.track-select').disabled")
                    window.evaluate_js("document.querySelector('.track-select').click()")
                    wait_for("document.getElementById('basket-count').textContent === '1'")
                    assert len(api.get_state()["basket"]) == 1
                    window.evaluate_js("document.getElementById('nav-settings').click()")
                    assert window.evaluate_js("document.getElementById('settings-dialog').open")
                    window.evaluate_js("document.querySelectorAll('input[name=quality]')[2].checked=true;document.getElementById('settings-form').requestSubmit()")
                    wait_for("!document.getElementById('settings-dialog').open")
                    assert api.get_state()["settings"]["quality"] == "256"
                    window.evaluate_js("document.getElementById('download-button').click()")
                    wait_for("document.getElementById('dock-title').textContent === 'Музыка сохранена'")
                    api._worker.join(5)
                    assert not api._worker.is_alive()
                    state = evaluate_async("pywebview.api.get_state()")
                    assert state["basket"] == [] and state["summary"] == {"saved": 1, "failed": 0}
                    wait_for("document.body.textContent.includes('Сохранено: 1')")
                    assert window.evaluate_js("uiErrors.length === 0"), window.evaluate_js("uiErrors")
                    window.resize(1000, 720)
                    time.sleep(0.4)
                    assert window.evaluate_js("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"
                    assert window.evaluate_js("isSecureContext && !!navigator.clipboard"), "Clipboard unavailable"
                    success.set()
                    print("WebView2 integration passed: bridge, rendering, selection, batch, XSS escaping, layout, clipboard capability")
                except Exception as error:
                    failure.append(error)
                finally:
                    window.destroy()

            timer = threading.Timer(35, window.destroy)
            timer.start()
            try:
                webview.start(check, gui="edgechromium", debug=False)
            finally:
                timer.cancel()
    if failure:
        raise failure[0]
    if not success.is_set():
        raise AssertionError("WebView integration did not finish")


if __name__ == "__main__":
    main()
