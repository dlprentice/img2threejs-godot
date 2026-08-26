from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .graph import validate_graph
from .intake import adapt_object_sculpt_spec
from .manifest import build_manifest


DEFAULT_WINDOWS_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
OWNED_OUTPUT_NAMES = {
    "source.spec.json",
    "constructive_graph.json",
    "asset.glb",
    "asset_manifest.json",
    "blender_report.json",
    "blender.stdout.log",
    "blender.stderr.log",
}


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


def _blender_path(explicit: Path | None) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
    elif os.environ.get("BLENDER_EXECUTABLE"):
        candidate = Path(os.environ["BLENDER_EXECUTABLE"]).expanduser().resolve()
    elif shutil.which("blender"):
        candidate = Path(shutil.which("blender")).resolve()
    else:
        candidate = DEFAULT_WINDOWS_BLENDER
    if not candidate.is_file():
        raise ValueError(f"Blender executable does not exist: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_identity(repository: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True, timeout=20
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    )
    if len(commit) != 40:
        raise RuntimeError("could not determine a full generator commit SHA")
    return commit, dirty


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_blender(command: list[str], *, cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    process = subprocess.Popen(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise TimeoutError(
            f"Blender build exceeded {timeout_seconds}s and its process tree was terminated\n"
            f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        ) from error
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _refuse_preexisting_outputs(output_directory: Path) -> None:
    existing = sorted(name for name in OWNED_OUTPUT_NAMES if (output_directory / name).exists())
    if existing:
        raise ValueError("output directory contains preexisting backend outputs: " + ", ".join(existing))


def _clean_failed_outputs(output_directory: Path) -> None:
    for name in ("asset.glb", "asset_manifest.json", "blender_report.json"):
        (output_directory / name).unlink(missing_ok=True)
    for temporary in output_directory.glob(".asset.*.glb"):
        if temporary.is_file():
            temporary.unlink(missing_ok=True)


def _validate_attempt_id(attempt_id: str) -> str:
    prefix = "attempt-"
    if not isinstance(attempt_id, str) or not attempt_id.startswith(prefix):
        raise ValueError("attempt_id must use attempt-<UUID> format")
    try:
        parsed = uuid.UUID(attempt_id[len(prefix) :])
    except ValueError as error:
        raise ValueError("attempt_id must use attempt-<UUID> format") from error
    if attempt_id != prefix + str(parsed):
        raise ValueError("attempt_id must use canonical lowercase attempt-<UUID> format")
    return attempt_id


def run(
    spec_path: Path,
    output_directory: Path,
    blender: Path | None = None,
    *,
    timeout_seconds: int = 300,
    attempt_id: str | None = None,
    control_plane_commit_sha: str | None = None,
    shared_toolchain_commit_sha: str | None = None,
    control_plane_tree_dirty: bool | None = None,
    shared_toolchain_tree_dirty: bool | None = None,
) -> dict:
    spec_path = spec_path.expanduser().resolve()
    output_directory = output_directory.expanduser().resolve()
    if not spec_path.is_file():
        raise ValueError(f"specification does not exist: {spec_path}")
    output_directory.mkdir(parents=True, exist_ok=True)
    _refuse_preexisting_outputs(output_directory)
    attempt_id = _validate_attempt_id(attempt_id or f"attempt-{uuid.uuid4()}")
    repository_root = Path(__file__).resolve().parents[3]
    generator_commit_sha, generator_tree_dirty = _git_identity(repository_root)
    source_copy = output_directory / "source.spec.json"
    source_copy.write_bytes(spec_path.read_bytes())
    graph = adapt_object_sculpt_spec(source_copy)
    graph_errors = validate_graph(graph)
    if graph_errors:
        raise ValueError("invalid graph:\n- " + "\n- ".join(graph_errors))
    graph_path = output_directory / "constructive_graph.json"
    _write_json_atomic(graph_path, graph)

    glb_path = output_directory / "asset.glb"
    report_path = output_directory / "blender_report.json"
    builder_path = Path(__file__).with_name("blender_build.py").resolve()
    blender_executable = _blender_path(blender)
    command = [
        str(blender_executable),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        "2",
        "--python",
        str(builder_path),
        "--",
        "--graph",
        str(graph_path),
        "--output",
        str(glb_path),
        "--report",
        str(report_path),
    ]
    command_contract = {
        "attemptId": attempt_id,
        "blenderExecutable": blender_executable.name,
        "builderSha256": _sha256(builder_path),
        "constructiveGraphSha256": _sha256(graph_path),
        "sourceSpecificationSha256": _sha256(source_copy),
        "generatorCommitSha": generator_commit_sha,
        "generatorTreeDirty": generator_tree_dirty,
        "controlPlaneCommitSha": control_plane_commit_sha,
        "controlPlaneTreeDirty": control_plane_tree_dirty,
        "sharedToolchainCommitSha": shared_toolchain_commit_sha,
        "sharedToolchainTreeDirty": shared_toolchain_tree_dirty,
        "flags": ["--background", "--factory-startup", "--disable-autoexec", "--python-exit-code=2"],
        "timeoutSeconds": timeout_seconds,
    }
    build_command_digest = hashlib.sha256(
        json.dumps(command_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    try:
        completed = _run_blender(command, cwd=repository_root, timeout_seconds=timeout_seconds)
    except Exception:
        _clean_failed_outputs(output_directory)
        raise
    (output_directory / "blender.stdout.log").write_text(completed.stdout, encoding="utf-8", newline="\n")
    (output_directory / "blender.stderr.log").write_text(completed.stderr, encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        _clean_failed_outputs(output_directory)
        raise RuntimeError(
            f"Blender build failed with exit code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    builder_report = json.loads(report_path.read_text(encoding="utf-8"))
    if builder_report.get("status") != "pass":
        raise RuntimeError(f"Blender report did not pass: {builder_report}")
    manifest = build_manifest(
        graph,
        glb_path,
        builder_report,
        graph_path=graph_path,
        provenance={
            "attemptId": attempt_id,
            "generatorCommitSha": generator_commit_sha,
            "generatorTreeDirty": generator_tree_dirty,
            "controlPlaneCommitSha": control_plane_commit_sha,
            "sharedToolchainCommitSha": shared_toolchain_commit_sha,
            "controlPlaneTreeDirty": control_plane_tree_dirty,
            "sharedToolchainTreeDirty": shared_toolchain_tree_dirty,
            "constructiveGraphSha256": _sha256(graph_path),
            "buildCommandDigest": build_command_digest,
        },
    )
    manifest_path = output_directory / "asset_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return {
        "status": "pass",
        "outputDirectory": str(output_directory),
        "glb": str(glb_path),
        "manifest": str(manifest_path),
        "blenderReport": str(report_path),
        "blenderStdout": completed.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a validated ObjectSculptSpec through the constrained Blender backend.")
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--attempt-id")
    parser.add_argument("--control-plane-commit-sha")
    parser.add_argument("--shared-toolchain-commit-sha")
    parser.add_argument("--control-plane-tree-dirty", choices=["true", "false"])
    parser.add_argument("--shared-toolchain-tree-dirty", choices=["true", "false"])
    args = parser.parse_args()
    try:
        result = run(
            args.spec,
            args.output,
            args.blender,
            timeout_seconds=args.timeout_seconds,
            attempt_id=args.attempt_id,
            control_plane_commit_sha=args.control_plane_commit_sha,
            shared_toolchain_commit_sha=args.shared_toolchain_commit_sha,
            control_plane_tree_dirty=None if args.control_plane_tree_dirty is None else args.control_plane_tree_dirty == "true",
            shared_toolchain_tree_dirty=None
            if args.shared_toolchain_tree_dirty is None
            else args.shared_toolchain_tree_dirty == "true",
        )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary reports concise failure.
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
