from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from backends.blender.examples.armored_vehicle_spec import make_armored_vehicle_spec
from backends.blender.runtime.run_backend import run as run_blender
from integrations.godot.run_validation import _parse_diagnostics, run


GODOT = os.environ.get("GODOT_EXECUTABLE")
BLENDER = os.environ.get("BLENDER_EXECUTABLE")
RUN_SABOTAGE = os.environ.get("RUN_ASSETFORGE_SABOTAGE") == "1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path, artifact_id: str, role: str) -> dict:
    return {
        "id": artifact_id,
        "role": role,
        "path": path.name,
        "sha256": _sha256(path),
        "byteSize": path.stat().st_size,
    }


def _minimal_artifact(root: Path) -> str:
    attempt_id = f"attempt-{uuid.uuid4()}"
    glb = root / "asset.glb"
    graph = root / "constructive_graph.json"
    stdout = root / "blender.stdout.log"
    stderr = root / "blender.stderr.log"
    glb.write_bytes(b"bounded-glb-fixture")
    graph.write_text("{}\n", encoding="utf-8")
    stdout.write_text("", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    manifest = {
        "generator": {
            "attemptId": attempt_id,
            "constructiveGraphSha256": _sha256(graph),
            "toolVersions": {},
        },
        "artifacts": [
            _artifact(glb, "asset-glb", "glb"),
            _artifact(graph, "constructive-graph", "constructive-graph"),
            _artifact(stdout, "blender-stdout", "process-log"),
            _artifact(stderr, "blender-stderr", "process-log"),
        ],
        "validationResults": [],
        "sockets": [],
        "lodLevels": [],
    }
    (root / "asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return attempt_id


def _png(path: Path, width: int = 960, height: int = 540) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    scanlines = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


class GodotRunnerIntegrityTests(unittest.TestCase):
    def test_render_selects_wayland_only_in_a_wayland_session(self) -> None:
        for wayland in ("", "wayland-1"):
            with self.subTest(wayland=wayland), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"WAYLAND_DISPLAY": wayland},
            ):
                root = Path(directory)
                _minimal_artifact(root)

                def runner(command, cwd, timeout):
                    if "--headless" in command:
                        self.assertNotIn("--display-driver", command)
                        return subprocess.CompletedProcess(command, 0, "", "")
                    if wayland:
                        self.assertEqual(command[command.index("--display-driver") + 1], "wayland")
                    else:
                        self.assertNotIn("--display-driver", command)
                    return subprocess.CompletedProcess(command, 1, "", "")

                with self.assertRaisesRegex(RuntimeError, "Godot render failed"):
                    run(root, Path("godot-for-test"), _runner=runner)

    def test_missing_optional_window_icon_protocol_is_reported_without_rejecting_asset(self) -> None:
        result = subprocess.CompletedProcess(["godot"], 0, "",
            "WARNING: xdg-toplevel-icon protocol not found! Cannot set window icon.\n")
        messages = _parse_diagnostics("render", result)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["code"], "godot-render-warning-allowed")

    def test_godot_selection_preserves_overrides_and_portable_fallback(self) -> None:
        for explicit, environment, has_dev, selected in (
            (True, True, True, "explicit-godot"),
            (False, True, True, "environment-godot"),
            (False, False, True, "godot-dev"),
            (False, False, False, "godot"),
        ):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _minimal_artifact(root)
                expected = root / selected

                def which(name):
                    return None if name == "godot-dev" and not has_dev else str(root / name)

                def runner(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                    self.assertEqual(str(expected), command[0])
                    return subprocess.CompletedProcess(command, 1, "", "")

                with patch.dict(os.environ, {"GODOT_EXECUTABLE": str(root / "environment-godot") if environment else ""}), patch(
                    "integrations.godot.run_validation.shutil.which", side_effect=which
                ), self.assertRaisesRegex(RuntimeError, "Godot import failed"):
                    run(root, godot=root / "explicit-godot" if explicit else None, _runner=runner)

    def test_stale_evidence_is_refused_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = _minimal_artifact(root)
            (root / "godot_validation.json").write_text('{"status":"pass"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "preexisting Godot evidence"):
                run(root, Path("missing-godot"), attempt_id=attempt, _runner=lambda *_: None)  # type: ignore[arg-type]

    def test_zero_exit_without_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = _minimal_artifact(root)

            def runner(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                self.assertFalse((cwd / ".godot").exists())
                self.assertEqual({"main.gd", "main.tscn", "project.godot"}, {path.name for path in cwd.iterdir() if path.is_file()})
                return subprocess.CompletedProcess(command, 0, "", "")

            with self.assertRaisesRegex(RuntimeError, "without fresh evidence"):
                run(root, Path("missing-godot"), attempt_id=attempt, _runner=runner)

    def test_warning_with_zero_exit_is_rejected(self) -> None:
        result = subprocess.CompletedProcess(["godot"], 0, "WARNING: unexpected import mutation\n", "")
        with self.assertRaisesRegex(RuntimeError, "disallowed diagnostics"):
            _parse_diagnostics("import", result)

    def test_stale_manifest_glb_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = _minimal_artifact(root)
            manifest_path = root / "asset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][0]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash or size is stale"):
                run(root, Path("missing-godot"), attempt_id=attempt, _runner=lambda *_: None)  # type: ignore[arg-type]

    def test_report_nonce_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = _minimal_artifact(root)
            calls = 0

            def runner(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                nonlocal calls
                calls += 1
                if calls == 2:
                    evidence = cwd / "evidence" / "current"
                    for name in ("rts.png", "rts_without_asset.png", "asset_mask.png"):
                        _png(evidence / name)
                    context = json.loads((cwd / "imports" / "current" / "validation_context.json").read_text())
                    hashes = {name: _sha256(evidence / name) for name in ("rts.png", "rts_without_asset.png", "asset_mask.png")}
                    report = {
                        "status": "pass",
                        "attemptId": context["attemptId"],
                        "glbSha256": context["glbSha256"],
                        "manifestSha256": context["manifestSha256"],
                        "nonce": "wrong",
                        "evidenceSha256": hashes,
                    }
                    (evidence / "godot_validation.json").write_text(json.dumps(report), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with self.assertRaisesRegex(RuntimeError, "binding mismatch for nonce"):
                run(root, Path("missing-godot"), attempt_id=attempt, _runner=runner)


@unittest.skipUnless(GODOT and BLENDER and RUN_SABOTAGE, "set tool paths and RUN_ASSETFORGE_SABOTAGE=1")
class GodotSabotageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.source = Path(cls.workspace.name) / "source"
        cls.source.mkdir()
        spec = cls.source / "vehicle.input.spec.json"
        spec.write_text(json.dumps(make_armored_vehicle_spec()), encoding="utf-8")
        cls.attempt = f"attempt-{uuid.uuid4()}"
        run_blender(spec, cls.source, Path(BLENDER), attempt_id=cls.attempt)

    def _copy(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "artifact"
        shutil.copytree(self.source, root)
        return temporary, root

    def _expect_failure(self, *, sabotage: str | None = None, mutate: Callable[[dict], None] | None = None) -> None:
        _, root = self._copy()
        if mutate:
            manifest_path = root / "asset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            mutate(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            run(root, Path(GODOT), attempt_id=self.attempt, _sabotage=sabotage)

    def test_hidden_and_off_camera_assets_fail(self) -> None:
        for sabotage in (
            "hidden",
            "off-camera",
            "below-floor",
            "one-component",
            "missing-material",
            "backface-culling",
        ):
            with self.subTest(sabotage=sabotage):
                self._expect_failure(sabotage=sabotage)

    def test_socket_and_hierarchy_corruption_fail(self) -> None:
        def socket(manifest: dict) -> None:
            manifest["sockets"][0]["transform"]["translation"][0] += 1.0
            manifest["sockets"][0]["transform"]["rotationQuaternion"] = [0.0, 0.7071068, 0.0, 0.7071068]

        def hierarchy(manifest: dict) -> None:
            next(value for value in manifest["meshNodes"] if value["id"] == "weapon")["parentId"] = "hull"

        self._expect_failure(mutate=socket)
        self._expect_failure(mutate=hierarchy)

    def test_collision_and_lod_corruption_fail(self) -> None:
        def collision(manifest: dict) -> None:
            manifest["collisionShapes"][0]["dimensions"][0] += 1.0
            manifest["collisionShapes"][0]["nodeId"] = "turret"

        def lod(manifest: dict) -> None:
            manifest["lodLevels"][1]["meshNodeIds"].pop()
            manifest["lodLevels"][1]["triangleCount"] = manifest["lodLevels"][0]["triangleCount"]

        self._expect_failure(mutate=collision)
        self._expect_failure(mutate=lod)


if __name__ == "__main__":
    unittest.main()
