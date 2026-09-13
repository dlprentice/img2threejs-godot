"""Opt-in native pose checks; requires Godot 4.7.2 and a working rendering backend."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from backends.process import run_bounded
from integrations.godot.preview_motion import PROJECT


@unittest.skipUnless(os.environ.get("RUN_MOTION_CLEARANCE_NATIVE") == "1",
                     "set RUN_MOTION_CLEARANCE_NATIVE=1 for native geometry checks")
class NativeClearanceTests(unittest.TestCase):
    def test_posed_geometry_and_explicit_failures(self):
        executable = os.environ.get("GODOT_EXECUTABLE") or shutil.which("godot")
        self.assertIsNotNone(executable, "set GODOT_EXECUTABLE or put Godot on PATH")
        for rendering_method in ("forward_plus", "gl_compatibility"):
            with self.subTest(rendering_method=rendering_method):
                self.check_native_fixture(executable, rendering_method)

    def check_native_fixture(self, executable, rendering_method):
        with tempfile.TemporaryDirectory(prefix="motion-clearance-", dir="/var/tmp") as temporary:
            project = Path(temporary)
            (project / "project.godot").write_text('config_version=5\n')
            shutil.copyfile(PROJECT / "clearance.gd", project / "clearance.gd")
            shutil.copyfile(Path(__file__).with_name("clearance_fixture.gd"), project / "fixture.gd")
            result = run_bounded([executable, "--path", str(project), "--script", "fixture.gd",
                                  "--audio-driver", "Dummy", "--rendering-method", rendering_method],
                                 cwd=project, timeout_seconds=60, label="Native surface fixture")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((project / "result.json").read_text())
            self.assertEqual(report["failures"], [])
            self.assertEqual(report["renderer"], rendering_method)


if __name__ == "__main__":
    unittest.main()
