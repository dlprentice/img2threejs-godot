from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backends.blender.runtime.path_safety import safe_asset_path
from backends.process import run_bounded


PROJECT_SOURCE = Path(__file__).with_name("validation_project")
PROJECT_FILES = ("project.godot", "main.gd", "main.tscn")
EVIDENCE_NAMES = ("godot_validation.json", "rts.png", "rts_without_asset.png", "asset_mask.png")
OUTPUT_NAMES = {
    *EVIDENCE_NAMES,
    "godot_import.stdout.log",
    "godot_import.stderr.log",
    "godot_render.stdout.log",
    "godot_render.stderr.log",
    "godot_validation",
}
ERROR_PATTERNS = (
    re.compile(r"(?i)\bSCRIPT ERROR\b"),
    re.compile(r"(?i)^\s*ERROR(?:\s|:)"),
    re.compile(r"^\s*E\s+\d{1,2}:\d{2}:\d{2}"),
)
WARNING_PATTERNS = (
    re.compile(r"(?i)^\s*WARNING(?:\s|:)"),
    re.compile(r"^\s*W\s+\d{1,2}:\d{2}:\d{2}"),
)
# Harmless messages must be matched in full. Unknown warnings fail the attempt.
ALLOWED_WARNING_PATTERNS = (
    re.compile(r"^WARNING: The --position argument is ignored by the current display server\.?$"),
)
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return run_bounded(command, cwd=cwd, timeout_seconds=timeout_seconds, label="Godot command")


def _write_process_logs(artifact_directory: Path, phase: str, result: subprocess.CompletedProcess[str]) -> None:
    (artifact_directory / f"godot_{phase}.stdout.log").write_text(result.stdout or "", encoding="utf-8", newline="\n")
    (artifact_directory / f"godot_{phase}.stderr.log").write_text(result.stderr or "", encoding="utf-8", newline="\n")


def _parse_diagnostics(phase: str, result: subprocess.CompletedProcess[str]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    rejected: list[str] = []
    for stream_name, content in (("stdout", result.stdout or ""), ("stderr", result.stderr or "")):
        for raw_line in content.splitlines():
            line = ANSI_PATTERN.sub("", raw_line).strip()
            if not line:
                continue
            if any(pattern.search(line) for pattern in ERROR_PATTERNS):
                messages.append({"code": f"godot-{phase}-error", "severity": "error", "text": f"{stream_name}: {line}"})
                rejected.append(line)
            elif any(pattern.search(line) for pattern in WARNING_PATTERNS):
                allowed = any(pattern.fullmatch(line) for pattern in ALLOWED_WARNING_PATTERNS)
                messages.append(
                    {
                        "code": f"godot-{phase}-warning-{'allowed' if allowed else 'unknown'}",
                        "severity": "warning",
                        "text": f"{stream_name}: {line}",
                    }
                )
                if not allowed:
                    rejected.append(line)
    if rejected:
        raise RuntimeError(f"Godot {phase} emitted disallowed diagnostics:\n- " + "\n- ".join(rejected))
    return messages


def _decode_png(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"not a PNG file: {path}")
    offset = 8
    width = height = bit_depth = color_type = 0
    compressed = bytearray()
    saw_end = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        crc = int.from_bytes(data[offset + 8 + length : offset + 12 + length], "big")
        if len(chunk) != length or zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != crc:
            raise ValueError(f"PNG has a truncated or corrupt {chunk_type!r} chunk: {path}")
        if chunk_type == b"IHDR":
            if length != 13:
                raise ValueError(f"PNG IHDR is invalid: {path}")
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth, color_type = chunk[8], chunk[9]
            if chunk[10:] != b"\x00\x00\x00":
                raise ValueError(f"interlaced or nonstandard PNG is unsupported: {path}")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            saw_end = True
            break
        offset += length + 12
    channels = {2: 3, 6: 4}.get(color_type)
    if not saw_end or width <= 0 or height <= 0 or bit_depth != 8 or channels is None:
        raise ValueError(f"PNG must be a complete 8-bit RGB/RGBA image: {path}")
    scanlines = zlib.decompress(bytes(compressed))
    stride = width * channels
    if len(scanlines) != height * (stride + 1):
        raise ValueError(f"PNG decoded scanline size is invalid: {path}")
    previous = bytearray(stride)
    decoded = bytearray()
    for row_index in range(height):
        start = row_index * (stride + 1)
        filter_type = scanlines[start]
        row = bytearray(scanlines[start + 1 : start + 1 + stride])
        if filter_type not in range(5):
            raise ValueError(f"PNG has an invalid filter: {path}")
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                row[index] = (row[index] + (left, up, upper_left)[distances.index(min(distances))]) & 0xFF
        decoded.extend(row)
        previous = row
    return {"width": width, "height": height, "pixelSha256": hashlib.sha256(decoded).hexdigest()}


def _add_artifact(manifest: dict, *, artifact_id: str, role: str, path: Path, base: Path) -> None:
    safe_path = safe_asset_path(base, path.relative_to(base).as_posix())
    manifest["artifacts"] = [value for value in manifest["artifacts"] if value["id"] != artifact_id]
    manifest["artifacts"].append(
        {
            "id": artifact_id,
            "role": role,
            "path": safe_path.relative_to(base).as_posix(),
            "sha256": _sha256(safe_path),
            "byteSize": safe_path.stat().st_size,
        }
    )


def _reconcile_artifacts(manifest: dict, base: Path) -> None:
    seen: set[str] = set()
    for artifact in manifest.get("artifacts", []):
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or artifact_id in seen:
            raise ValueError(f"manifest contains an invalid or duplicate artifact ID: {artifact_id!r}")
        seen.add(artifact_id)
        path = safe_asset_path(base, artifact.get("path"))
        if not path.is_file():
            raise ValueError(f"manifest artifact is missing: {artifact_id}")
        if path.stat().st_size != artifact.get("byteSize") or _sha256(path) != artifact.get("sha256"):
            raise ValueError(f"manifest artifact hash or size is stale: {artifact_id}")
    graph_hash = manifest.get("generator", {}).get("constructiveGraphSha256")
    graph_artifact = next((value for value in manifest.get("artifacts", []) if value.get("id") == "constructive-graph"), None)
    if not graph_artifact or graph_artifact.get("sha256") != graph_hash:
        raise ValueError("constructive graph provenance does not match its artifact record")


def _refuse_preexisting_outputs(artifact_directory: Path) -> None:
    existing = sorted(name for name in OUTPUT_NAMES if (artifact_directory / name).exists())
    if existing:
        raise ValueError("artifact directory contains preexisting Godot evidence: " + ", ".join(existing))


def _verify_fresh_file(path: Path, process_started_ns: int) -> None:
    if not path.is_file():
        raise RuntimeError(f"Godot exited without fresh evidence file: {path.name}")
    if path.stat().st_mtime_ns < process_started_ns:
        raise RuntimeError(f"Godot evidence predates the render process: {path.name}")


def run(
    artifact_directory: Path,
    godot: Path | None = None,
    *,
    attempt_id: str | None = None,
    timeout_seconds: int = 180,
    _runner: Callable[[list[str], Path, int], subprocess.CompletedProcess[str]] | None = None,
    _sabotage: str | None = None,
) -> dict:
    artifact_directory = artifact_directory.expanduser().resolve()
    glb_path = artifact_directory / "asset.glb"
    manifest_path = artifact_directory / "asset_manifest.json"
    if not glb_path.is_file() or not manifest_path.is_file():
        raise ValueError("artifact directory must contain asset.glb and asset_manifest.json")
    _refuse_preexisting_outputs(artifact_directory)
    godot_command = godot or os.environ.get("GODOT_EXECUTABLE") or shutil.which("godot")
    if not godot_command:
        raise ValueError("Godot was not found; set GODOT_EXECUTABLE or pass --godot")
    executable = Path(godot_command).expanduser().resolve()
    if not executable.is_file() and _runner is None:
        raise ValueError(f"Godot executable does not exist: {executable}")
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(source_manifest, dict):
        raise ValueError("asset_manifest.json must contain an object")
    _reconcile_artifacts(source_manifest, artifact_directory)
    manifest_attempt = source_manifest.get("generator", {}).get("attemptId")
    attempt_id = attempt_id or manifest_attempt
    if not isinstance(attempt_id, str) or not attempt_id.startswith("attempt-"):
        raise ValueError("attempt_id must be supplied in attempt-<UUID> format by the manifest or command line")
    if manifest_attempt is not None and manifest_attempt != attempt_id:
        raise ValueError("attempt_id does not match the generator manifest")

    runner = _runner or _run_command
    nonce = secrets.token_hex(32)
    input_manifest_sha256 = _sha256(manifest_path)
    context = {
        "attemptId": attempt_id,
        "glbSha256": _sha256(glb_path),
        "manifestSha256": input_manifest_sha256,
        "nonce": nonce,
        "sabotage": _sabotage,
    }
    import_messages: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="assetforge-godot-", dir="/var/tmp") as temporary_name:
        project = Path(temporary_name) / "validation_project"
        project.mkdir()
        for name in PROJECT_FILES:
            shutil.copyfile(PROJECT_SOURCE / name, project / name)
        import_directory = project / "imports" / "current"
        evidence_directory = project / "evidence" / "current"
        import_directory.mkdir(parents=True)
        evidence_directory.mkdir(parents=True)
        shutil.copyfile(glb_path, import_directory / "asset.glb")
        shutil.copyfile(manifest_path, import_directory / "asset_manifest.json")
        _write_json_atomic(import_directory / "validation_context.json", context)
        if (project / ".godot").exists() or any((evidence_directory / name).exists() for name in EVIDENCE_NAMES):
            raise RuntimeError("fresh validation project unexpectedly contains cache or evidence")

        import_result = runner([str(executable), "--headless", "--path", str(project), "--import", "--quit"], project, timeout_seconds)
        _write_process_logs(artifact_directory, "import", import_result)
        import_messages = _parse_diagnostics("import", import_result)
        if import_result.returncode != 0:
            raise RuntimeError(f"Godot import failed with exit code {import_result.returncode}")

        render_started_ns = time.time_ns()
        render_result = runner(
            [
                str(executable),
                "--path",
                str(project),
                "--rendering-method",
                "forward_plus",
                "--resolution",
                "960x540",
                "--position",
                "5000,5000",
            ],
            project,
            timeout_seconds,
        )
        _write_process_logs(artifact_directory, "render", render_result)
        render_messages = _parse_diagnostics("render", render_result)
        if render_result.returncode != 0:
            raise RuntimeError(f"Godot render failed with exit code {render_result.returncode}")

        project_paths = {name: evidence_directory / name for name in EVIDENCE_NAMES}
        for path in project_paths.values():
            _verify_fresh_file(path, render_started_ns)
        report = json.loads(project_paths["godot_validation.json"].read_text(encoding="utf-8"))
        if report.get("status") != "pass":
            raise RuntimeError(f"Godot validation report did not pass: {report}")
        for key in ("attemptId", "glbSha256", "manifestSha256", "nonce"):
            if report.get(key) != context[key]:
                raise RuntimeError(f"Godot report binding mismatch for {key}")
        for name in ("rts.png", "rts_without_asset.png", "asset_mask.png"):
            expected_hash = report.get("evidenceSha256", {}).get(name)
            if expected_hash != _sha256(project_paths[name]):
                raise RuntimeError(f"Godot report hash mismatch for {name}")
            png = _decode_png(project_paths[name])
            if png["width"] != 960 or png["height"] != 540:
                raise RuntimeError(f"Godot evidence has unexpected dimensions: {name} {png}")

        for name, source in project_paths.items():
            shutil.copyfile(source, artifact_directory / name)
        wrapper_directory = artifact_directory / "godot_validation"
        wrapper_directory.mkdir()
        for name in PROJECT_FILES:
            shutil.copyfile(PROJECT_SOURCE / name, wrapper_directory / name)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_specs = (
        ("rts-preview", "preview-render", artifact_directory / "rts.png"),
        ("rts-without-asset", "preview-render", artifact_directory / "rts_without_asset.png"),
        ("asset-mask", "preview-render", artifact_directory / "asset_mask.png"),
        ("godot-validation-report", "validation-report", artifact_directory / "godot_validation.json"),
        ("godot-wrapper-scene", "godot-scene", wrapper_directory / "main.tscn"),
        ("godot-import-stdout", "process-log", artifact_directory / "godot_import.stdout.log"),
        ("godot-import-stderr", "process-log", artifact_directory / "godot_import.stderr.log"),
        ("godot-render-stdout", "process-log", artifact_directory / "godot_render.stdout.log"),
        ("godot-render-stderr", "process-log", artifact_directory / "godot_render.stderr.log"),
    )
    for artifact_id, role, path in artifact_specs:
        _add_artifact(manifest, artifact_id=artifact_id, role=role, path=path, base=artifact_directory)
    manifest["generator"]["toolVersions"]["godot"] = report["engineVersion"]
    manifest["validationResults"] = [value for value in manifest["validationResults"] if value["id"] != "godot-import-runtime"]
    manifest["validationResults"].append(
        {
            "id": "godot-import-runtime",
            "validator": "fresh per-attempt Godot validation project",
            "validatorVersion": report["engineVersion"],
            "status": "pass",
            "checkedAt": _timestamp(),
            "messages": [
                {
                    "code": "godot-semantic-pass",
                    "severity": "info",
                    "text": f"Validated {report['meshCount']} imported meshes, semantic transforms, collision, explicit LOD switching, and asset-specific pixels.",
                },
                *import_messages,
                *render_messages,
            ],
            "artifactIds": [artifact_id for artifact_id, _, _ in artifact_specs],
        }
    )
    manifest["godotPackaging"] = {
        "godotVersion": report["engineVersion"],
        "status": "pass",
        "scenePath": "godot_validation/main.tscn",
        "wrapperKind": "wrapper",
        "attemptId": attempt_id,
        "validationInputManifestSha256": input_manifest_sha256,
        "validationNonce": nonce,
        "importMessages": import_messages,
        "mappedSocketIds": [value["id"] for value in manifest["sockets"]],
        "mappedLodIds": [value["id"] for value in manifest["lodLevels"]],
    }
    _reconcile_artifacts(manifest, artifact_directory)
    _write_json_atomic(manifest_path, manifest)
    return {
        "status": "pass",
        "attemptId": attempt_id,
        "report": str(artifact_directory / "godot_validation.json"),
        "screenshot": str(artifact_directory / "rts.png"),
        "engineVersion": report["engineVersion"],
        "renderingDriver": report["renderingDriver"],
        "videoAdapter": report["videoAdapter"],
        "importMessages": import_messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import and render an asset in a fresh, correlated Godot validation project.")
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run(
                    args.artifact_dir,
                    args.godot,
                    attempt_id=args.attempt_id,
                    timeout_seconds=args.timeout_seconds,
                ),
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary reports concise failure.
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
