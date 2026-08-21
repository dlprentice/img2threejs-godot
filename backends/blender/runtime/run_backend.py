from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .graph import validate_graph
from .intake import adapt_object_sculpt_spec
from .manifest import build_manifest


DEFAULT_WINDOWS_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")


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
    elif shutil.which("blender"):
        candidate = Path(shutil.which("blender")).resolve()
    else:
        candidate = DEFAULT_WINDOWS_BLENDER
    if not candidate.is_file():
        raise ValueError(f"Blender executable does not exist: {candidate}")
    return candidate


def run(spec_path: Path, output_directory: Path, blender: Path | None = None) -> dict:
    spec_path = spec_path.expanduser().resolve()
    output_directory = output_directory.expanduser().resolve()
    if not spec_path.is_file():
        raise ValueError(f"specification does not exist: {spec_path}")
    output_directory.mkdir(parents=True, exist_ok=True)
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
    command = [
        str(_blender_path(blender)),
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
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[3], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Blender build failed with exit code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    builder_report = json.loads(report_path.read_text(encoding="utf-8"))
    if builder_report.get("status") != "pass":
        raise RuntimeError(f"Blender report did not pass: {builder_report}")
    manifest = build_manifest(graph, glb_path, builder_report)
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
    args = parser.parse_args()
    try:
        result = run(args.spec, args.output, args.blender)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary reports concise failure.
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
