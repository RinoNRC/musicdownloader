from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

from music_core import (
    QUALITIES, Cancelled, Track, download_track, friendly_error,
    load_settings, save_settings, search_tracks,
)


class DesktopAPI:
    def __init__(self):
        self._lock = threading.RLock()
        self._window = None
        self._worker = None
        self._cancel = threading.Event()
        self._revision = 0
        self._settings = load_settings()
        self._results: list[Track] = []
        self._basket: dict[str, Track] = {}
        self._busy = "idle"
        self._query = ""
        self._status = "Найдите музыку для следующей поездки"
        self._progress = 0.0
        self._current_track = None
        self._logs = []
        self._summary = None
        self._closing = False

    def _changed(self):
        self._revision += 1

    def _log(self, text, level="info"):
        self._logs.append({"time": time.strftime("%H:%M:%S"), "text": str(text), "level": level})
        self._logs = self._logs[-300:]
        self._changed()

    def _error(self, error):
        text = friendly_error(error) if isinstance(error, Exception) else str(error)
        self._log(text, "error")
        return {"ok": False, "error": text}

    def _available(self):
        return self._busy == "idle" and not self._closing

    def get_state(self):
        with self._lock:
            return copy.deepcopy({
                "revision": self._revision,
                "settings": self._settings,
                "results": [asdict(track) for track in self._results],
                "basket": [asdict(track) for track in self._basket.values()],
                "busy": self._busy,
                "query": self._query,
                "status": self._status,
                "progress": self._progress,
                "current_track": asdict(self._current_track) if self._current_track else None,
                "logs": self._logs,
                "summary": self._summary,
                "closing": self._closing,
            })

    def _settings_patch(self, patch):
        if not isinstance(patch, dict):
            raise ValueError("Некорректные настройки.")
        settings = self._settings.copy()
        for key, value in patch.items():
            if key == "quality" and value in QUALITIES:
                settings[key] = value
            elif key == "source" and value in ("YouTube", "SoundCloud"):
                settings[key] = value
            elif key == "ascii_names" and isinstance(value, bool):
                settings[key] = value
            elif key == "folder" and isinstance(value, str) and value.strip():
                folder = Path(value.strip()).expanduser()
                if not folder.is_absolute():
                    raise ValueError("Укажите полный путь к папке, например D:\\Music.")
                settings[key] = str(folder)
            else:
                raise ValueError("Некорректное значение настройки: " + str(key))
        save_settings(settings)
        self._settings = settings
        self._changed()

    def update_settings(self, patch):
        with self._lock:
            if not self._available():
                return {"ok": False, "error": "Дождитесь завершения текущей операции."}
            try:
                self._settings_patch(patch)
                return {"ok": True}
            except (OSError, ValueError, TypeError) as error:
                return self._error(error)

    def search(self, query, source):
        with self._lock:
            if not self._available():
                return {"ok": False, "error": "Дождитесь завершения текущей операции."}
            if not isinstance(query, str) or not query.strip():
                return {"ok": False, "error": "Введите название песни или ссылку."}
            if source not in ("YouTube", "SoundCloud"):
                return {"ok": False, "error": "Неизвестная площадка."}
            self._settings["source"] = source
            try:
                save_settings(self._settings)
            except OSError as error:
                self._log("Не удалось сохранить настройки: " + str(error), "error")
            self._query = query.strip()
            self._busy = "search"
            self._status = "Ищем подходящие треки…"
            self._summary = None
            self._progress = 0
            self._changed()
            self._worker = threading.Thread(target=self._search_worker, args=(self._query, source), daemon=True)
            self._worker.start()
            return {"ok": True}

    def _search_worker(self, query, source):
        try:
            tracks = search_tracks(query, source)
            with self._lock:
                self._results = tracks
                self._status = f"Найдено треков: {len(tracks)}" if tracks else "Ничего не найдено. Попробуйте другой запрос."
                self._log(f"{source} · {query} · результатов: {len(tracks)}")
        except Exception as error:
            with self._lock:
                self._status = "Не удалось выполнить поиск. Подробности — в журнале."
                self._error(error)
        finally:
            with self._lock:
                self._busy = "idle"
                self._changed()

    def set_selected(self, url, selected):
        with self._lock:
            if not self._available():
                return {"ok": False, "error": "Выбор недоступен во время операции."}
            if not isinstance(url, str) or not isinstance(selected, bool):
                return {"ok": False, "error": "Некорректный выбор трека."}
            if selected:
                track = next((track for track in self._results if track.url == url), None)
                if track is None:
                    return {"ok": False, "error": "Трек не найден в результатах поиска."}
                self._basket.setdefault(url, track)
            else:
                self._basket.pop(url, None)
            self._changed()
            return {"ok": True}

    def select_all(self, selected):
        with self._lock:
            if not self._available() or not isinstance(selected, bool):
                return {"ok": False, "error": "Сейчас нельзя изменить выбор."}
            for track in self._results:
                if selected:
                    self._basket.setdefault(track.url, track)
                else:
                    self._basket.pop(track.url, None)
            self._changed()
            return {"ok": True}

    def remove_track(self, url):
        return self.set_selected(url, False)

    def clear_basket(self):
        with self._lock:
            if not self._available():
                return {"ok": False, "error": "Дождитесь завершения текущей операции."}
            self._basket.clear()
            self._changed()
            return {"ok": True}

    def choose_folder(self):
        import webview

        with self._lock:
            if not self._available() or self._window is None:
                return {"ok": False, "error": "Сейчас нельзя выбрать папку."}
            current = Path(self._settings["folder"]).expanduser()
        try:
            chosen = self._window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=str(current) if current.is_dir() else str(Path.home()),
            )
            if not chosen:
                return {"ok": True, "folder": None}
            result = self.update_settings({"folder": chosen[0]})
            if result["ok"]:
                result["folder"] = chosen[0]
            return result
        except Exception as error:
            with self._lock:
                return self._error(error)

    def open_folder(self):
        with self._lock:
            folder = Path(self._settings["folder"]).expanduser()
        try:
            if not folder.is_dir():
                return {"ok": False, "error": "Папка появится после первого скачивания."}
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
            return {"ok": True}
        except OSError as error:
            with self._lock:
                return self._error(error)

    def start_download(self):
        with self._lock:
            if not self._available():
                return {"ok": False, "error": "Дождитесь завершения текущей операции."}
            if not self._basket:
                return {"ok": False, "error": "Сначала выберите треки для скачивания."}
            folder = Path(self._settings["folder"]).expanduser()
            if not folder.is_absolute():
                return {"ok": False, "error": "Укажите полный путь к папке в настройках."}
            self._cancel.clear()
            self._busy = "download"
            self._progress = 0
            self._summary = None
            self._status = "Подготовка загрузки…"
            selected = list(self._basket.values())
            settings = self._settings.copy()
            settings["folder"] = str(folder)
            self._log(f"Очередь: {len(selected)} · MP3 {settings['quality']} кбит/с")
            self._worker = threading.Thread(target=self._download_worker, args=(selected, settings), daemon=True)
            self._worker.start()
            return {"ok": True}

    def _download_worker(self, selected, settings):
        saved = failed = 0
        try:
            for index, track in enumerate(selected):
                if self._cancel.is_set():
                    break
                with self._lock:
                    self._current_track = track
                    self._status = f"{index + 1}/{len(selected)} · Подготовка…"
                    self._log(f"[{index + 1}/{len(selected)}] {track.title}")

                def report(fraction, detail):
                    with self._lock:
                        self._progress = (index + max(0, min(fraction, 1))) / len(selected)
                        if not self._cancel.is_set():
                            self._status = f"{index + 1}/{len(selected)} · {detail}"
                        self._changed()

                try:
                    result = download_track(track, Path(settings["folder"]), settings["quality"],
                                            settings["ascii_names"], self._cancel, report)
                    saved += 1
                    with self._lock:
                        self._basket.pop(track.url, None)
                        self._log(f"Сохранено: {result.name}", "success")
                except Exception as error:
                    if self._cancel.is_set() or isinstance(error, Cancelled):
                        break
                    failed += 1
                    with self._lock:
                        self._error(error)
                report(1, "Обработка очереди…")
        except Exception as error:
            failed += 1
            with self._lock:
                self._error(error)
        finally:
            with self._lock:
                stopped = self._cancel.is_set()
                self._summary = {"saved": saved, "failed": failed}
                self._status = f"{'Остановлено' if stopped else 'Готово'} · сохранено: {saved} · ошибок: {failed}"
                if not stopped:
                    self._progress = 1
                self._current_track = None
                self._busy = "idle"
                self._log(self._status)

    def cancel_download(self):
        with self._lock:
            if self._busy != "download":
                return {"ok": False, "error": "Нет активной загрузки."}
            self._cancel.set()
            self._status = "Останавливаем загрузку…"
            self._changed()
            return {"ok": True}

    def _on_closing(self):
        with self._lock:
            if self._closing:
                return False
            downloading = self._busy == "download"
        if downloading:
            if not self._window.create_confirmation_dialog(
                "Закрыть Music / Drive?", "Остановить загрузку и выйти? Уже готовые MP3 останутся в папке.",
            ):
                return False
        with self._lock:
            self._closing = True
            self._changed()
            if self._busy != "download":
                return True
            self._cancel.set()
            self._status = "Останавливаем загрузку перед выходом…"
            worker = self._worker

        def finish():
            worker.join()
            self._window.events.closing -= self._on_closing
            self._window.destroy()

        threading.Thread(target=finish, daemon=True).start()
        return False
