import os
import tkinter as tk

import customtkinter as ctk


class ClipboardEntry(ctk.CTkEntry):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clipboard_menu = tk.Menu(self, tearoff=False)
        for label, action, shortcut in (
            ("Вырезать", "cut", "Ctrl+X"),
            ("Копировать", "copy", "Ctrl+C"),
            ("Вставить", "paste", "Ctrl+V"),
        ):
            self.clipboard_menu.add_command(
                label=label, accelerator=shortcut,
                command=lambda command=action: self.clipboard_action(command),
            )
        self.clipboard_menu.add_separator()
        self.clipboard_menu.add_command(
            label="Выделить всё", accelerator="Ctrl+A",
            command=lambda: self.clipboard_action("select_all"),
        )
        self.bind("<Control-KeyPress>", self._control_key)
        self.bind("<Shift-Insert>", lambda _: self.clipboard_action("paste"))
        self.bind("<Button-3>", self._show_clipboard_menu)

    def _control_key(self, event):
        # Windows virtual-key codes stay the same in Russian and English layouts.
        if os.name == "nt":
            action = {65: "select_all", 67: "copy", 86: "paste", 88: "cut"}.get(event.keycode)
        else:
            action = {"a": "select_all", "c": "copy", "v": "paste", "x": "cut"}.get(event.keysym.lower())
        if action:
            return self.clipboard_action(action)
        return None

    def clipboard_action(self, action):
        if self.cget("state") != "normal":
            return "break"
        try:
            if action == "select_all":
                self.select_range(0, "end")
                self.icursor("end")
            elif action in ("copy", "cut"):
                if self.select_present():
                    text = self.get()[self.index("sel.first"):self.index("sel.last")]
                    self.clipboard_clear()
                    self.clipboard_append(text)
                    if action == "cut":
                        self.delete("sel.first", "sel.last")
            elif action == "paste":
                text = self.clipboard_get()
                text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                if self.select_present():
                    self.delete("sel.first", "sel.last")
                self.insert("insert", text)
        except tk.TclError:
            pass
        return "break"

    def _show_clipboard_menu(self, event):
        if self.cget("state") != "normal":
            return "break"
        self.focus_set()
        state = "normal" if self.select_present() else "disabled"
        self.clipboard_menu.entryconfigure(0, state=state)
        self.clipboard_menu.entryconfigure(1, state=state)
        try:
            self.clipboard_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.clipboard_menu.grab_release()
        return "break"
