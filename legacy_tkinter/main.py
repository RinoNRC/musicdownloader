from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ui_helpers import ClipboardEntry
from music_core import (
    Cancelled, Track, download_track, duration_text, friendly_error,
    load_settings, save_settings, search_tracks,
)


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#10141e"
PANEL = "#191f2d"
ACCENT = "#487bff"
MUTED = "#9ca9c1"


class MusicDownloader(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Music Downloader · музыка в дорогу")
        self.geometry("1200x860")
        self.minsize(1000, 740)
        self.configure(fg_color=BG)
        self.settings = load_settings()
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.downloading = False
        self.closing = False
        self.tracks: list[Track] = []
        self.selection: list[tk.BooleanVar] = []
        self.track_boxes = []
        self.track_rows = []
        self.basket: dict[str, Track] = {}
        self.basket_buttons = []
        self.query = tk.StringVar()
        self.folder = tk.StringVar(value=self.settings["folder"])
        self.quality = tk.StringVar(value=self.settings["quality"])
        self.source = tk.StringVar(value=self.settings["source"])
        self.ascii_names = tk.BooleanVar(value=self.settings["ascii_names"])
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(80, self._poll)
        self.search_entry.focus_set()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 14))
        ctk.CTkLabel(header, text="MUSIC / DRIVE", font=("Segoe UI", 27, "bold"),
                     text_color="#f3f6ff").pack(anchor="w")
        ctk.CTkLabel(header, text="Найдите трек. Сохраните MP3. Возьмите музыку в дорогу.",
                     text_color=MUTED, font=("Segoe UI", 13)).pack(anchor="w", pady=(3, 0))

        search = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14)
        search.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 14))
        search.grid_columnconfigure(0, weight=1)
        self.search_entry = ClipboardEntry(
            search, textvariable=self.query, placeholder_text="Исполнитель и название песни или ссылка на трек",
            height=44, font=("Segoe UI", 14), border_width=0, fg_color="#242d40",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(14, 10), pady=14)
        self.search_entry.bind("<Return>", lambda _: self._search())
        self.source_menu = ctk.CTkOptionMenu(search, values=["YouTube", "SoundCloud"],
                                              variable=self.source, width=140, height=44,
                                              fg_color="#29344a", button_color="#34425c")
        self.source_menu.grid(row=0, column=1, padx=(0, 10))
        self.search_button = ctk.CTkButton(search, text="Найти", width=110, height=44,
                                             fg_color=ACCENT, command=self._search)
        self.search_button.grid(row=0, column=2, padx=(0, 14))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 14))
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0, minsize=310)
        content.grid_rowconfigure(0, weight=1)
        results = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=14)
        results.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        results.grid_columnconfigure(0, weight=1)
        results.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(results, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        self.result_label = ctk.CTkLabel(toolbar, text="Результаты поиска", font=("Segoe UI", 15, "bold"))
        self.result_label.pack(side="left")
        self.select_button = ctk.CTkButton(toolbar, text="Выбрать все", width=115, height=28,
                                             fg_color="#29344a", command=self._select_all, state="disabled")
        self.select_button.pack(side="right")
        self.results_frame = ctk.CTkScrollableFrame(results, fg_color="transparent")
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self.results_frame.grid_columnconfigure(0, weight=1)
        self._empty_results("Здесь появятся найденные треки", "Введите название песни в строке выше и нажмите Enter.")

        basket_panel = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=14, width=310)
        basket_panel.grid(row=0, column=1, sticky="nsew")
        basket_panel.grid_columnconfigure(0, weight=1)
        basket_panel.grid_rowconfigure(2, weight=1)
        self.basket_label = ctk.CTkLabel(basket_panel, text="К скачиванию · 0", font=("Segoe UI", 15, "bold"))
        self.basket_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(basket_panel, text="Выбор сохраняется между поисками",
                     text_color=MUTED, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=16)
        self.basket_frame = ctk.CTkScrollableFrame(basket_panel, fg_color="transparent", width=278)
        self.basket_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.basket_frame.grid_columnconfigure(0, weight=1)
        self.clear_basket_button = ctk.CTkButton(
            basket_panel, text="Очистить список", height=30, fg_color="#29344a",
            command=self._clear_basket, state="disabled",
        )
        self.clear_basket_button.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

        settings = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14)
        settings.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 14))
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings, text="Сохранить в", text_color=MUTED).grid(row=0, column=0, padx=(16, 12), pady=(14, 8))
        self.folder_entry = ClipboardEntry(settings, textvariable=self.folder, height=34,
                                             fg_color="#242d40", border_width=0)
        self.folder_entry.grid(row=0, column=1, sticky="ew", pady=(14, 8))
        self.folder_button = ctk.CTkButton(settings, text="Выбрать папку", width=130, height=34,
                                              fg_color="#29344a", command=self._choose_folder)
        self.folder_button.grid(row=0, column=2, padx=(10, 16), pady=(14, 8))
        options = ctk.CTkFrame(settings, fg_color="transparent")
        options.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        ctk.CTkLabel(options, text="MP3 /", text_color=MUTED).pack(side="left", padx=(0, 8))
        self.quality_menu = ctk.CTkOptionMenu(options, values=["128", "192", "256", "320"], variable=self.quality,
                                               width=85, fg_color="#29344a", button_color="#34425c")
        self.quality_menu.pack(side="left")
        ctk.CTkLabel(options, text="кбит/с  ·  44,1 кГц  ·  стерео", text_color=MUTED).pack(side="left", padx=10)
        self.ascii_box = ctk.CTkCheckBox(options, text="Имена файлов латиницей", variable=self.ascii_names,
                                            checkbox_width=20, checkbox_height=20, font=("Segoe UI", 12))
        self.ascii_box.pack(side="right")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=28)
        bottom.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(bottom, text="Готово к поиску", text_color=MUTED, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew", columnspan=3, pady=(0, 3))
        self.progress = ctk.CTkProgressBar(bottom, height=6, progress_color=ACCENT)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.progress.set(0)
        self.open_button = ctk.CTkButton(bottom, text="Открыть папку", fg_color="#29344a", command=self._open_folder, height=40)
        self.open_button.grid(row=2, column=0, sticky="w")
        self.cancel_button = ctk.CTkButton(bottom, text="Остановить", fg_color="#613743", hover_color="#804654",
                                              command=self._cancel, state="disabled", width=130, height=40)
        self.cancel_button.grid(row=2, column=1, padx=10)
        self.download_button = ctk.CTkButton(bottom, text="Скачать MP3", fg_color=ACCENT, command=self._download,
                                                state="disabled", width=220, height=40, font=("Segoe UI", 14, "bold"))
        self.download_button.grid(row=2, column=2)
        self.log = ctk.CTkTextbox(self, height=74, fg_color="#141a26", text_color=MUTED, font=("Consolas", 11))
        self.log.grid(row=5, column=0, sticky="ew", padx=28, pady=(12, 0))
        self.log.configure(state="disabled")
        ctk.CTkLabel(self, text="Сохраняйте только записи, на скачивание которых у вас есть право.",
                     text_color="#74809a", font=("Segoe UI", 11)).grid(row=6, column=0, pady=(5, 10))
        self._render_basket()

    def _empty_results(self, title, subtitle):
        for child in self.results_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.results_frame, text=title, text_color=MUTED,
                     font=("Segoe UI", 17)).grid(row=0, column=0, pady=(38, 5))
        ctk.CTkLabel(self.results_frame, text=subtitle, text_color="#74809a",
                     wraplength=420).grid(row=1, column=0, pady=(0, 30))

    def _show_tracks(self, tracks):
        self.tracks = tracks
        self.selection = []
        self.track_boxes = []
        self.track_rows = []
        for child in self.results_frame.winfo_children():
            child.destroy()
        self.result_label.configure(text=f"Результаты поиска · {len(tracks)}")
        if not tracks:
            self._empty_results("Ничего не найдено", "Уточните название или выберите другую площадку.")
        for index, track in enumerate(tracks):
            row = ctk.CTkFrame(self.results_frame, fg_color="#222b3c", corner_radius=8)
            row.grid(row=index, column=0, sticky="ew", padx=2, pady=4)
            row.grid_columnconfigure(1, weight=1)
            self.track_rows.append(row)
            selected = tk.BooleanVar(value=track.url in self.basket)
            self.selection.append(selected)
            checkbox = ctk.CTkCheckBox(row, text="", variable=selected, width=24, checkbox_width=22,
                                          checkbox_height=22, command=self._selection_changed)
            checkbox.grid(row=0, column=0, rowspan=2, padx=(12, 4), pady=12)
            self.track_boxes.append(checkbox)
            # A fixed character limit keeps long remote titles from expanding the window.
            title = track.title if len(track.title) <= 75 else track.title[:72] + "…"
            ctk.CTkLabel(row, text=title, anchor="w", font=("Segoe UI", 13, "bold"),
                         wraplength=420, justify="left").grid(row=0, column=1, sticky="w", pady=(8, 0))
            ctk.CTkLabel(row, text=track.artist[:50], anchor="w", text_color=MUTED,
                         font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(0, 8))
            ctk.CTkLabel(row, text=duration_text(track.duration), width=60,
                         text_color=MUTED).grid(row=0, column=2, rowspan=2, padx=10)
        self._selection_changed()

    def _selection_changed(self):
        for track, var in zip(self.tracks, self.selection):
            if var.get():
                self.basket.setdefault(track.url, track)
            else:
                self.basket.pop(track.url, None)
        self._sync_selection()
        self._render_basket()

    def _sync_selection(self):
        for track, var, row in zip(self.tracks, self.selection, self.track_rows):
            selected = track.url in self.basket
            var.set(selected)
            row.configure(fg_color="#243c65" if selected else "#222b3c",
                          border_width=1 if selected else 0, border_color=ACCENT)
        self._update_selection_controls()

    def _update_selection_controls(self):
        count = len(self.basket)
        self.download_button.configure(text=f"Скачать все MP3 · {count}" if count else "Скачать MP3",
                                       state="normal" if count and not self.busy else "disabled")
        all_selected = bool(self.selection) and all(var.get() for var in self.selection)
        self.select_button.configure(text="Снять выбор" if all_selected else "Выбрать все",
                                     state="normal" if self.tracks and not self.busy else "disabled")
        self.clear_basket_button.configure(state="normal" if count and not self.busy else "disabled")
        for button in self.basket_buttons:
            button.configure(state="disabled" if self.busy else "normal")

    def _render_basket(self):
        for child in self.basket_frame.winfo_children():
            child.destroy()
        self.basket_buttons = []
        self.basket_label.configure(text=f"К скачиванию · {len(self.basket)}")
        if not self.basket:
            ctk.CTkLabel(self.basket_frame, text="Отметьте нужные треки\nв результатах поиска.\n\nЗатем найдите следующую песню —\nвыбранные треки останутся здесь.",
                         text_color=MUTED, wraplength=250, justify="left").grid(row=0, column=0, padx=8, pady=20)
        for index, (url, track) in enumerate(self.basket.items()):
            row = ctk.CTkFrame(self.basket_frame, fg_color="#222b3c", corner_radius=8)
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)
            title = track.title if len(track.title) <= 70 else track.title[:67] + "…"
            ctk.CTkLabel(row, text=title, font=("Segoe UI", 12, "bold"), wraplength=200,
                         justify="left", anchor="w").grid(row=0, column=0, sticky="w", padx=(10, 4), pady=(8, 0))
            ctk.CTkLabel(row, text=duration_text(track.duration), text_color=MUTED,
                         font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
            remove = ctk.CTkButton(row, text="×", width=28, height=28, fg_color="#34425c",
                                       command=lambda key=url: self._remove_from_basket(key))
            remove.grid(row=0, column=1, rowspan=2, padx=(0, 8))
            self.basket_buttons.append(remove)
        self._update_selection_controls()

    def _remove_from_basket(self, url):
        if self.busy:
            return
        self.basket.pop(url, None)
        self._sync_selection()
        self._render_basket()

    def _clear_basket(self):
        if self.busy:
            return
        self.basket.clear()
        self._sync_selection()
        self._render_basket()

    def _select_all(self):
        if self.busy:
            return
        value = not all(var.get() for var in self.selection)
        for var in self.selection:
            var.set(value)
        self._selection_changed()

    def _set_busy(self, busy, downloading=False):
        self.busy = busy
        self.downloading = downloading
        state = "disabled" if busy else "normal"
        for widget in (self.search_button, self.source_menu, self.search_entry, self.folder_entry,
                       self.folder_button, self.quality_menu, self.ascii_box, *self.track_boxes):
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if downloading else "disabled")
        self._update_selection_controls()

    def _search(self):
        if self.busy or not self.query.get().strip():
            return
        query, source = self.query.get().strip(), self.source.get()
        self._set_busy(True)
        self.status_label.configure(text="Ищем треки…")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._save()

        def worker():
            try:
                self.events.put(("results", search_tracks(query, source)))
            except Exception as error:
                self.events.put(("search_error", friendly_error(error)))

        threading.Thread(target=worker, daemon=True).start()

    def _download(self):
        if self.busy:
            return
        selected = list(self.basket.values())
        if not selected:
            return
        raw_folder = self.folder.get().strip()
        if not raw_folder:
            messagebox.showwarning("Папка не выбрана", "Выберите папку для сохранения MP3.")
            return
        folder = Path(raw_folder).expanduser()
        if not folder.is_absolute():
            messagebox.showwarning("Папка", "Укажите полный путь к папке, например D:\\Music.")
            return
        quality, ascii_names = self.quality.get(), self.ascii_names.get()
        self._save()
        self.cancel_event.clear()
        self._set_busy(True, downloading=True)
        self.progress.set(0)
        self.status_label.configure(text="Подготовка загрузки…")
        self._write_log(f"Очередь: {len(selected)} · MP3 {quality} кбит/с")

        def worker():
            succeeded = failed = 0
            for index, track in enumerate(selected):
                if self.cancel_event.is_set():
                    break
                self.events.put(("log", f"[{index + 1}/{len(selected)}] {track.title}"))
                last_update = 0.0

                def report(fraction, detail):
                    nonlocal last_update
                    now = time.monotonic()
                    if now - last_update < 0.15 and fraction < 0.8:
                        return
                    last_update = now
                    self.events.put(("progress", ((index + fraction) / len(selected),
                                                 f"{index + 1}/{len(selected)} · {detail}")))

                try:
                    result = download_track(track, folder, quality, ascii_names, self.cancel_event, report)
                    succeeded += 1
                    self.events.put(("downloaded", track.url))
                    self.events.put(("log", f"Сохранено: {result.name}"))
                except Exception as error:
                    if self.cancel_event.is_set() or isinstance(error, Cancelled):
                        break
                    failed += 1
                    self.events.put(("log", "Ошибка: " + friendly_error(error)))
                self.events.put(("progress", ((index + 1) / len(selected), "Обработка очереди…")))
            self.events.put(("finished", (succeeded, failed, self.cancel_event.is_set())))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            for _ in range(100):
                event, value = self.events.get_nowait()
                if event in ("results", "search_error"):
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress.set(0)
                    self._set_busy(False)
                    if event == "results":
                        self._show_tracks(value)
                        self.status_label.configure(text=f"Найдено: {len(value)} · в списке к скачиванию: {len(self.basket)}")
                    else:
                        self.status_label.configure(text="Не удалось выполнить поиск")
                        self._write_log(value)
                        messagebox.showerror("Ошибка поиска", value[:2000])
                elif event == "progress":
                    self.progress.set(value[0])
                    self.status_label.configure(text=value[1])
                elif event == "log":
                    self._write_log(value)
                elif event == "downloaded":
                    self.basket.pop(value, None)
                    self._sync_selection()
                    self._render_basket()
                elif event == "finished":
                    succeeded, failed, cancelled = value
                    self._set_busy(False)
                    text = f"{'Остановлено' if cancelled else 'Готово'} · сохранено: {succeeded} · ошибок: {failed}"
                    self.status_label.configure(text=text)
                    self._write_log(text)
                    if not cancelled:
                        self.progress.set(1)
                    if self.closing:
                        self.destroy()
                        return
                    if failed:
                        messagebox.showwarning("Не все треки скачаны", "Подробности ошибок — в журнале внизу окна.\n"
                                               "Можно попробовать другую площадку или запустить update.bat.")
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_label.configure(text="Останавливаем… Ждём завершения текущей операции.")

    def _choose_folder(self):
        current = Path(self.folder.get()).expanduser()
        chosen = filedialog.askdirectory(title="Папка для MP3 — можно выбрать флешку",
                                         initialdir=str(current) if current.is_dir() else str(Path.home()))
        if chosen:
            self.folder.set(chosen)
            self._save()

    def _open_folder(self):
        try:
            folder = Path(self.folder.get()).expanduser()
            if not folder.is_dir():
                messagebox.showinfo("Папка пока не существует", "Папка появится после первого скачивания.")
                return
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                subprocess.Popen(["open" if __import__("sys").platform == "darwin" else "xdg-open", str(folder)])
        except OSError as error:
            messagebox.showerror("Не удалось открыть папку", str(error))

    def _save(self):
        try:
            save_settings({"folder": self.folder.get(), "quality": self.quality.get(),
                           "source": self.source.get(), "ascii_names": self.ascii_names.get()})
        except OSError as error:
            self._write_log("Не удалось сохранить настройки: " + str(error))

    def _write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S") + "  " + str(text) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 400:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _close(self):
        if self.closing:
            return
        if self.downloading:
            if not messagebox.askyesno("Выйти?", "Остановить загрузку и закрыть приложение?\nУже готовые MP3 останутся в папке."):
                return
            self.closing = True
            self._cancel()
            return
        self._save()
        self.destroy()


def main():
    app = MusicDownloader()
    app.mainloop()


if __name__ == "__main__":
    main()
