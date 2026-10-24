import unittest
from unittest.mock import MagicMock, patch

import main


class LauncherTests(unittest.TestCase):
    @patch("main.webview.start")
    @patch("main.webview.create_window")
    @patch("main.DesktopAPI")
    def test_only_explicit_public_methods_are_exposed(self, api_class, create_window, start):
        window = create_window.return_value
        window.events.closing = MagicMock()
        main.main()
        self.assertNotIn("js_api", create_window.call_args.kwargs)
        methods = window.expose.call_args.args
        expected = ("get_state", "search", "set_selected", "select_all", "remove_track", "clear_basket",
                    "update_settings", "choose_folder", "open_folder", "start_download", "cancel_download")
        self.assertEqual(methods, tuple(getattr(api_class.return_value, name) for name in expected))
        self.assertEqual(start.call_args.kwargs["gui"], "edgechromium")


if __name__ == "__main__":
    unittest.main()
