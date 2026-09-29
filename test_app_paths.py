import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app_paths import user_data_dir


class AppPathTests(unittest.TestCase):
    def test_windows_keeps_existing_memory_location(self):
        with patch("app_paths.sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": "local-data"}, clear=True):
            self.assertEqual(user_data_dir(), Path("local-data/FlyBrainPet"))

    def test_mac_uses_application_support(self):
        with patch("app_paths.sys.platform", "darwin"), patch.dict(os.environ, {}, clear=True), patch("app_paths.Path.home", return_value=Path("home")):
            self.assertEqual(user_data_dir(), Path("home/Library/Application Support/FlyBrainPet"))

    def test_explicit_isolation_wins_on_both_platforms(self):
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch("app_paths.sys.platform", platform), patch.dict(os.environ, {"FLYBRAINPET_DATA_DIR": "isolated"}):
                self.assertEqual(user_data_dir(), Path("isolated"))
