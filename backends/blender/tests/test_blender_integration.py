from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from backends.blender.examples.armored_vehicle_spec import make_armored_vehicle_spec
from backends.blender.runtime.run_backend import run


BLENDER = os.environ.get("BLENDER_EXECUTABLE")


@unittest.skipUnless(BLENDER, "set BLENDER_EXECUTABLE to run the headless Blender integration test")
class BlenderIntegrationTests(unittest.TestCase):
    def test_armored_vehicle_exports_measured_reduced_lod(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            spec = temporary / "vehicle.spec.json"
            spec.write_text(json.dumps(make_armored_vehicle_spec()), encoding="utf-8")
            result = run(spec, temporary / "output", Path(BLENDER))
            self.assertEqual("pass", result["status"])
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            levels = {value["level"]: value["triangleCount"] for value in manifest["lodLevels"]}
            self.assertLess(levels[1], levels[0])
            self.assertEqual(6, len(manifest["meshNodes"]))
            self.assertEqual(1, len(manifest["collisionShapes"]))
            self.assertEqual(1, len(manifest["pivots"]))
            self.assertEqual(2, len(manifest["sockets"]))


if __name__ == "__main__":
    unittest.main()
