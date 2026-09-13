"""Opt-in native pose checks; requires Godot 4.7.2 and a working rendering backend."""

import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from backends.process import run_bounded
from integrations.godot.preview_motion import PROJECT, run


def write_pulse_glb(path):
    """One skinned triangle with a pulse wholly between two 30 Hz bake samples."""
    binary = bytearray()
    views, accessors = [], []

    def accessor(rows, kind, component=5126, bounds=False):
        binary.extend(b"\0" * (-len(binary) % 4))
        offset = len(binary)
        format_code = {5126: "f", 5121: "B", 5123: "H"}[component]
        stored_rows = []
        for row in rows:
            format_string = "<" + format_code * len(row)
            encoded_row = struct.pack(format_string, *row)
            binary.extend(encoded_row)
            stored_rows.append(struct.unpack(format_string, encoded_row))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(binary) - offset})
        value = {"bufferView": len(views) - 1, "componentType": component, "count": len(rows), "type": kind}
        if bounds:
            value.update(min=[min(column) for column in zip(*stored_rows)],
                         max=[max(column) for column in zip(*stored_rows)])
        accessors.append(value)
        return len(accessors) - 1

    positions = accessor([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "VEC3", bounds=True)
    joints = accessor([(0, 0, 0, 0)] * 3, "VEC4", 5121)
    weights = accessor([(1, 0, 0, 0)] * 3, "VEC4")
    indices = accessor([(0,), (1,), (2,)], "SCALAR", 5123)
    binds = accessor([(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)], "MAT4")
    times = accessor([(index / 120,) for index in range(5)], "SCALAR", bounds=True)
    translations = accessor([(0, -0.1 if index == 1 else 0, 0) for index in range(5)], "VEC3")
    binary.extend(b"\0" * (-len(binary) % 4))
    document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [{"name": "Fixture", "children": [1, 2]}, {"name": "Hips"},
                          {"name": "Surface", "mesh": 0, "skin": 0}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": positions, "JOINTS_0": joints,
                                                            "WEIGHTS_0": weights}, "indices": indices}]}],
                "skins": [{"joints": [1], "skeleton": 1, "inverseBindMatrices": binds}],
                "animations": [{"name": "Pulse", "channels": [{"sampler": 0, "target": {"node": 1, "path": "translation"}}],
                                "samplers": [{"input": times, "output": translations, "interpolation": "LINEAR"}]}],
                "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
                     + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
                     + struct.pack("<II", len(binary), 0x004E4942) + binary)


@unittest.skipUnless(os.environ.get("RUN_MOTION_CLEARANCE_NATIVE") == "1",
                     "set RUN_MOTION_CLEARANCE_NATIVE=1 for native geometry checks")
class NativeClearanceTests(unittest.TestCase):
    def test_import_rate_retains_a_short_skinned_motion_pulse(self):
        with tempfile.TemporaryDirectory(prefix="motion-pulse-", dir="/var/tmp") as temporary:
            root = Path(temporary)
            source = root / "pulse.glb"
            write_pulse_glb(source)
            samples = {}
            for import_fps in (30, 120):
                record = run(source, root / f"preview-{import_fps}", animation="Pulse", fps=120,
                             duration=5 / 120, measure_floor_y=0, import_fps=import_fps, timeout=60)
                self.assertEqual(record["animationImportFps"], import_fps)
                self.assertEqual(len(record["frames"]), 5)
                samples[import_fps] = record["frames"][1]["clearance"]["minimumY"]
            self.assertAlmostEqual(samples[30], 0, delta=0.0001)
            self.assertAlmostEqual(samples[120], -0.1, delta=0.0001)

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
