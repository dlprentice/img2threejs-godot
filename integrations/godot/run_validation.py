from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_WINDOWS_GODOT = Path(r"C:\Tools\Godot\bin\Godot_console.exe")
PROJECT = Path(__file__).with_name("validation_project")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    value = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict) -> None:
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


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=False, timeout=180)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Godot command failed with exit code {completed.returncode}\nCOMMAND: {' '.join(command)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def _add_artifact(manifest: dict, *, artifact_id: str, role: str, path: Path, base: Path) -> None:
    relative = path.relative_to(base).as_posix()
    manifest["artifacts"] = [value for value in manifest["artifacts"] if value["id"] != artifact_id]
    manifest["artifacts"].append(
        {"id": artifact_id, "role": role, "path": relative, "sha256": _sha256(path), "byteSize": path.stat().st_size}
    )


def run(artifact_directory: Path, godot: Path | None = None) -> dict:
    artifact_directory = artifact_directory.expanduser().resolve()
    glb_path = artifact_directory / "asset.glb"
    manifest_path = artifact_directory / "asset_manifest.json"
    if not glb_path.is_file() or not manifest_path.is_file():
        raise ValueError("artifact directory must contain asset.glb and asset_manifest.json")
    executable = (godot or DEFAULT_WINDOWS_GODOT).expanduser().resolve()
    if not executable.is_file():
        raise ValueError(f"Godot executable does not exist: {executable}")

    import_directory = PROJECT / "imports" / "current"
    evidence_directory = PROJECT / "evidence" / "current"
    import_directory.mkdir(parents=True, exist_ok=True)
    evidence_directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(glb_path, import_directory / "asset.glb")
    shutil.copy2(manifest_path, import_directory / "asset_manifest.json")

    import_result = _run([str(executable), "--headless", "--path", str(PROJECT), "--import", "--quit"])
    render_result = _run(
        [
            str(executable),
            "--path",
            str(PROJECT),
            "--rendering-method",
            "forward_plus",
            "--resolution",
            "960x540",
            "--position",
            "5000,5000",
        ]
    )
    project_report = evidence_directory / "godot_validation.json"
    project_screenshot = evidence_directory / "rts.png"
    if not project_report.is_file() or not project_screenshot.is_file():
        raise RuntimeError("Godot exited without both required evidence files")
    report = json.loads(project_report.read_text(encoding="utf-8"))
    if report.get("status") != "pass":
        raise RuntimeError(f"Godot validation report did not pass: {report}")

    screenshot = artifact_directory / "rts.png"
    validation_report = artifact_directory / "godot_validation.json"
    shutil.copy2(project_screenshot, screenshot)
    shutil.copy2(project_report, validation_report)
    wrapper_directory = artifact_directory / "godot_validation"
    wrapper_directory.mkdir(parents=True, exist_ok=True)
    for name in ("project.godot", "main.tscn", "main.gd"):
        shutil.copy2(PROJECT / name, wrapper_directory / name)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _add_artifact(manifest, artifact_id="rts-preview", role="preview-render", path=screenshot, base=artifact_directory)
    _add_artifact(manifest, artifact_id="godot-validation-report", role="validation-report", path=validation_report, base=artifact_directory)
    _add_artifact(
        manifest,
        artifact_id="godot-wrapper-scene",
        role="godot-scene",
        path=wrapper_directory / "main.tscn",
        base=artifact_directory,
    )
    manifest["generator"]["toolVersions"]["godot"] = report["engineVersion"]
    manifest["validationResults"] = [value for value in manifest["validationResults"] if value["id"] != "godot-import-runtime"]
    manifest["validationResults"].append(
        {
            "id": "godot-import-runtime",
            "validator": "isolated Godot validation project",
            "validatorVersion": report["engineVersion"],
            "status": "pass",
            "checkedAt": _timestamp(),
            "messages": [
                {
                    "code": "godot-import-pass",
                    "severity": "info",
                    "text": f"Imported {report['meshCount']} meshes, hid {report['hiddenLod1Count']} far-LOD meshes, and rendered the RTS evidence view.",
                }
            ],
            "artifactIds": ["asset-glb", "rts-preview", "godot-validation-report"],
        }
    )
    manifest["godotPackaging"] = {
        "godotVersion": report["engineVersion"],
        "status": "pass",
        "scenePath": "godot_validation/main.tscn",
        "wrapperKind": "wrapper",
        "importMessages": [],
        "mappedSocketIds": [value["id"] for value in manifest["sockets"]],
        "mappedLodIds": [value["id"] for value in manifest["lodLevels"]],
    }
    _write_json_atomic(manifest_path, manifest)
    return {
        "status": "pass",
        "report": str(validation_report),
        "screenshot": str(screenshot),
        "engineVersion": report["engineVersion"],
        "renderingDriver": report["renderingDriver"],
        "videoAdapter": report["videoAdapter"],
        "importStdout": import_result.stdout,
        "renderStdout": render_result.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import and render a generated asset in the isolated Godot validation project.")
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--godot", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.artifact_dir, args.godot), indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary reports concise failure.
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
