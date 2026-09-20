from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
from unittest.mock import patch

from integrations.godot.preview_motion import inspect_glb, run, vector


def write_glb(path: Path, **extra) -> None:
    data = json.dumps({"asset": {"version": "2.0"}, **extra}).encode()
    data += b" " * (-len(data) % 4)
    path.write_bytes(b"glTF" + struct.pack("<IIII", 2, 20 + len(data), len(data), 0x4E4F534A) + data)


def write_png(path: Path, width=1280, height=720) -> None:
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * width * 3) * height))
                     + chunk(b"IEND", b""))


class MotionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="motion-preview-test-", dir="/var/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "input.glb"
        write_glb(self.source)
        self.godot = self.root / "godot"
        self.godot.touch()
        self.output = self.root / "preview"

    def launch(self, **kwargs):
        return run(self.source, self.output, godot=self.godot, **kwargs)

    def fake_result(self, command, *, cwd, timeout_seconds, label, width=1280):
        request = json.loads((cwd / "request.json").read_text())
        output = Path(request["output"])
        record = {"status": "complete", "sourceSha256": request["sourceSha256"], "frames": [],
                  "animationImportFps": request["importFps"],
                  "players": [{"path": "AnimationPlayer", "clips": [{"name": "walk"}]}]}
        if request["animation"] is not None:
            for index in range(request["frameCount"]):
                filename = f"frame-{index:05d}.png"
                write_png(output / filename, width=width)
                record["frames"].append({"file": filename, "dimensions": [1280, 720],
                                         "sha256": hashlib.sha256((output / filename).read_bytes()).hexdigest()})
        (output / "preview.json").write_text(json.dumps(record))
        return subprocess.CompletedProcess(command, 0, "preview complete\n", "")

    def test_engine_selection_preserves_overrides_and_portable_fallback(self):
        for explicit, environment, has_dev, selected in (
            (True, True, True, "explicit-godot"),
            (False, True, True, "environment-godot"),
            (False, False, True, "godot-dev"),
            (False, False, False, "godot"),
        ):
            with self.subTest(selected=selected):
                expected = self.root / selected
                expected.touch()
                self.output = self.root / f"preview-{selected}"

                def which(name):
                    return None if name == "godot-dev" and not has_dev else str(self.root / name)

                def runner(command, **kwargs):
                    self.assertEqual(command[0], str(expected))
                    return self.fake_result(command, **kwargs)

                with patch.dict(os.environ, {"GODOT_EXECUTABLE": str(self.root / "environment-godot") if environment else ""}), patch(
                    "integrations.godot.preview_motion.shutil.which", side_effect=which,
                ):
                    run(self.source, self.output, godot=self.root / "explicit-godot" if explicit else None, _runner=runner)

    def test_self_contained_input_rejects_external_resources(self):
        for reference in ("texture.png", "../outside.bin", "https://example.com/model.bin"):
            with self.subTest(reference=reference):
                write_glb(self.source, images=[{"uri": reference}])
                with self.assertRaisesRegex(ValueError, "self-contained"):
                    inspect_glb(self.source)
        write_glb(self.source, images=[{"uri": "data:image/png;base64,AA=="}])
        self.assertEqual(len(inspect_glb(self.source)), 64)
        write_glb(self.source, extras={"provenance": {"uri": "https://example.com/source"}})
        self.assertEqual(len(inspect_glb(self.source)), 64)

    def test_malformed_glb_rejected_before_creating_output(self):
        self.source.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "GLB"):
            self.launch()
        self.assertFalse(self.output.exists())

    def test_invalid_parameters_do_not_create_output(self):
        for kwargs in ({"fps": 0}, {"fps": 121}, {"fps": 2.5}, {"duration": float("nan")},
                       {"duration": 61}, {"duration": 0}, {"ortho_size": -1},
                       {"camera_center": (0, float("inf"), 0)}, {"camera_offset": (0, 1, 0)},
                       {"skeleton_path": "rig"}, {"animation": " "}, {"timeout": 0},
                       {"rendering_method": "unknown"}, {"loop": "automatic"},
                       {"measure_floor_y": 0}, {"animation": "walk", "measure_floor_y": float("inf")},
                       {"animation": "walk", "surface_material": "Sole"},
                       {"animation": "walk", "measure_floor_y": 0, "surface_material": " "},
                       {"import_fps": 0}, {"import_fps": 241}, {"import_fps": True},
                       {"import_fps": float("nan")}, {"import_fps": "30"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.launch(**kwargs)
            self.assertFalse(self.output.exists())

    def test_existing_directory_and_dangling_symlink_are_preserved(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.launch()
        self.assertEqual(marker.read_text(), "keep")
        self.output = self.root / "link"
        self.output.symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.launch()
        self.assertTrue(self.output.is_symlink())

    def test_listing_uses_runtime_project_without_import_and_copies_source(self):
        def runner(command, **kwargs):
            self.assertIn("--headless", command)
            self.assertNotIn("--import", command)
            self.assertNotIn("--editor", command)
            self.assertEqual((kwargs["cwd"] / "source.glb").read_bytes(), self.source.read_bytes())
            return self.fake_result(command, **kwargs)
        result = self.launch(_runner=runner)
        self.assertEqual(result["players"][0]["clips"][0]["name"], "walk")
        self.assertEqual(result["animationImportFps"], 30)
        self.assertFalse(list(self.output.glob("*.png")))

    def test_capture_propagates_explicit_controls_and_fixed_frames(self):
        def runner(command, **kwargs):
            self.assertNotIn("--headless", command)
            self.assertEqual(command[command.index("--fixed-fps") + 1], "2")
            self.assertEqual(command[command.index("--resolution") + 1], "1280x720")
            self.assertEqual(command[command.index("--rendering-method") + 1], "forward_plus")
            request = json.loads((kwargs["cwd"] / "request.json").read_text())
            self.assertEqual(request["animation"], "walk")
            self.assertEqual(request["playerPath"], "rig/AnimationPlayer")
            self.assertEqual(request["followBone"], "pelvis")
            self.assertEqual(request["skeletonPath"], "rig/Skeleton3D")
            self.assertEqual(request["cameraCenter"], [1, 2, 3])
            self.assertEqual(request["frameCount"], 3)
            self.assertEqual(request["loop"], "linear")
            return self.fake_result(command, **kwargs)
        result = self.launch(animation="walk", player_path="rig/AnimationPlayer", fps=2, duration=1.1,
                             camera_center=(1, 2, 3), follow_bone="pelvis", skeleton_path="rig/Skeleton3D",
                             loop="linear", _runner=runner)
        self.assertEqual(len(result["frames"]), 3)

    def test_import_rate_is_independent_of_output_frame_count(self):
        def runner(command, **kwargs):
            request = json.loads((kwargs["cwd"] / "request.json").read_text())
            self.assertEqual(request["importFps"], 59.94)
            self.assertEqual(request["fps"], 2)
            return self.fake_result(command, **kwargs)
        result = self.launch(animation="walk", fps=2, duration=1, import_fps=59.94, _runner=runner)
        self.assertEqual(result["animationImportFps"], 59.94)
        self.assertEqual(len(result["frames"]), 2)

    def test_wrong_import_rate_in_native_record_fails(self):
        def runner(command, **kwargs):
            result = self.fake_result(command, **kwargs)
            path = self.output / "preview.json"
            record = json.loads(path.read_text())
            record["animationImportFps"] = 30
            path.write_text(json.dumps(record))
            return result
        with self.assertRaisesRegex(RuntimeError, "import rate"):
            self.launch(import_fps=120, _runner=runner)

    def test_actual_wrong_png_dimensions_fail_even_when_record_claims_correct_size(self):
        def runner(command, **kwargs):
            return self.fake_result(command, **kwargs, width=640)
        with self.assertRaisesRegex(RuntimeError, "dimensions"):
            self.launch(animation="walk", fps=1, duration=1, _runner=runner)

    def test_measurement_reports_intersection_without_rejecting_capture(self):
        def runner(command, **kwargs):
            request = json.loads((kwargs["cwd"] / "request.json").read_text())
            self.assertEqual(request["measureFloorY"], 1.5)
            self.assertEqual(request["surfaceMaterial"], "Boot Sole")
            self.assertTrue((kwargs["cwd"] / "clearance.gd").is_file())
            result = self.fake_result(command, **kwargs)
            path = self.output / "preview.json"
            record = json.loads(path.read_text())
            record["frames"][0]["clearance"] = {
                "minimumY": 1.4, "referencedVertexCount": 3, "belowFloorVertexCount": 1,
            }
            path.write_text(json.dumps(record))
            return result
        result = self.launch(animation="walk", fps=1, duration=1, measure_floor_y=1.5,
                             surface_material="Boot Sole", _runner=runner)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["frames"][0]["clearance"]["belowFloorVertexCount"], 1)

    def test_missing_or_invalid_surface_measurements_fail(self):
        values = [None, [], {},
                  {"minimumY": float("nan"), "referencedVertexCount": 3, "belowFloorVertexCount": 0},
                  {"minimumY": True, "referencedVertexCount": 3, "belowFloorVertexCount": 0},
                  {"minimumY": 0, "referencedVertexCount": 0, "belowFloorVertexCount": 0},
                  {"minimumY": 0, "referencedVertexCount": 3, "belowFloorVertexCount": 4}]
        for index, value in enumerate(values):
            self.output = self.root / f"measurement-{index}"
            def runner(command, **kwargs):
                result = self.fake_result(command, **kwargs)
                path = self.output / "preview.json"
                record = json.loads(path.read_text())
                record["frames"][0]["clearance"] = value
                path.write_text(json.dumps(record))
                return result
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "surface measurement"):
                self.launch(animation="walk", fps=1, duration=1, measure_floor_y=0, _runner=runner)

    def test_failed_process_keeps_logs_and_is_not_success(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 2, "", "animation missing")
        with self.assertRaisesRegex(RuntimeError, "exit 2"):
            self.launch(_runner=runner)
        self.assertEqual((self.output / "stderr.log").read_text(), "animation missing")

    def test_truncated_png_with_intact_header_fails(self):
        def runner(command, **kwargs):
            result = self.fake_result(command, **kwargs)
            frame = self.output / "frame-00000.png"
            frame.write_bytes(frame.read_bytes()[:24])
            return result
        with self.assertRaisesRegex(RuntimeError, "changed after native decoding"):
            self.launch(animation="walk", fps=1, duration=1, _runner=runner)

    def test_timeout_retains_the_native_diagnostic(self):
        def runner(command, **kwargs):
            raise TimeoutError("native render timed out; partial stdout")
        with self.assertRaises(TimeoutError):
            self.launch(_runner=runner)
        self.assertIn("partial stdout", (self.output / "stderr.log").read_text())

    def test_vector_parser(self):
        self.assertEqual(vector("-1,2.5,0"), (-1.0, 2.5, 0.0))
        for value in ("1,2", "nan,2,3", "x,2,3"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                vector(value)


if __name__ == "__main__":
    unittest.main()
