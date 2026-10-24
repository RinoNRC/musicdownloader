from pathlib import Path

import webview

from desktop_api import DesktopAPI


def main():
    api = DesktopAPI()
    window = webview.create_window(
        "Music / Drive",
        url=str(Path(__file__).parent / "web" / "index.html"),
        width=1320,
        height=900,
        min_size=(1000, 720),
        background_color="#101116",
        text_select=True,
    )
    window.expose(
        api.get_state, api.search, api.set_selected, api.select_all,
        api.remove_track, api.clear_basket, api.update_settings,
        api.choose_folder, api.open_folder, api.start_download, api.cancel_download,
    )
    api._window = window
    window.events.closing += api._on_closing
    webview.start(gui="edgechromium", debug=False, private_mode=True, localization={
        "global.ok": "ОК", "global.cancel": "Отмена", "global.quit": "Выйти",
    })


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from release_selftest import run

        run(sys.argv[2])
    else:
        main()
