import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class SingleInstanceTests(unittest.TestCase):
    def test_existing_instance_is_notified_to_show_window(self):
        source = inspect.getsource(main.main)

        self.assertIn("notify_existing_instance()", source)
        self.assertIn("attach_single_instance_socket", source)

    def test_app_base_dir_uses_exe_parent_when_frozen(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", r"C:\tools\VM Sync\VM Sync.exe"):
            self.assertEqual(Path(r"C:\tools\VM Sync"), main.app_base_dir())

    def test_configure_tcl_tk_uses_pyinstaller_bundle_paths(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", r"C:\tools\VM Sync\_internal", create=True), \
                patch.dict(os.environ, {}, clear=True):
            main.configure_tcl_tk()

            self.assertEqual(
                r"C:\tools\VM Sync\_internal\tcl\tcl8.6",
                os.environ["TCL_LIBRARY"],
            )
            self.assertEqual(
                r"C:\tools\VM Sync\_internal\tcl\tk8.6",
                os.environ["TK_LIBRARY"],
            )


if __name__ == "__main__":
    unittest.main()
