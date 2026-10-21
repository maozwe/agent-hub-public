import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import desktop


class DesktopTests(unittest.TestCase):
    def test_initialization_isolated_and_preserves_operator_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = desktop.initialize(Path(directory))
            data = json.loads(path.read_text())
            self.assertEqual(data["agents"], [])
            self.assertEqual(Path(data["database"]).parent, Path(directory))
            path.write_text('{"preserved":true}')
            desktop.initialize(Path(directory))
            self.assertEqual(json.loads(path.read_text()), {"preserved": True})

    def test_frozen_command_does_not_relaunch_python_script(self):
        with patch.object(desktop.sys, "frozen", True, create=True):
            self.assertEqual(desktop.command("--worker", "--once"), [desktop.sys.executable, "--worker", "--once"])
