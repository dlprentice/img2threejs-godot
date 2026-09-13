"""Optional native Godot GLB clip listing and deterministic PNG motion preview."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends.process import run_bounded

PROJECT = Path(__file__).with_name("motion_preview")
WIDTH, HEIGHT = 1280, 720


def vector(text: str) -> tuple[float, float, float]:
    try:
        value = tuple(float(part) for part in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected three finite comma-separated numbers") from error
    if len(value) != 3 or not all(math.isfinite(part) for part in value):
        raise argparse.ArgumentTypeError("expected three finite comma-separated numbers")
    return value


def inspect_glb(source: Path) -> str:
    """Reject external resource references before the native loader sees the input."""
    data = source.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("input must be a GLB 2.0 file")
    version, length, json_length, chunk_type = struct.unpack_from("<IIII", data, 4)
    if version != 2 or length != len(data) or chunk_type != 0x4E4F534A or 20 + json_length > len(data):
        raise ValueError("invalid GLB 2.0 header or JSON chunk")
    document = json.loads(data[20:20 + json_length])
    if (not isinstance(document, dict) or not isinstance(document.get("asset"), dict)
            or document["asset"].get("version") != "2.0"):
        raise ValueError("input must describe glTF 2.0")
    # Restrict URI-bearing resources/extensions, while retaining ordinary provenance
    # URLs in application-specific extras (which the glTF loader does not resolve).
    def check(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "extras":
                    continue
                if key == "uri" and (not isinstance(child, str) or not child.startswith("data:")):
                    raise ValueError("input must be self-contained; external URI references are unsupported")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(document)
    return hashlib.sha256(data).hexdigest()


def run(source: Path, output: Path, *, animation: str | None = None,
        player_path: str | None = None, fps: int = 30, duration: float = 4.0,
        ortho_size: float = 3.5, camera_center: tuple[float, float, float] = (0, 1, 0),
        camera_offset: tuple[float, float, float] = (4, 2, 6),
        follow_bone: str | None = None, skeleton_path: str | None = None,
        godot: Path | None = None, timeout: int = 180,
        rendering_method: str = "forward_plus", loop: str = "source",
        measure_floor_y: float | None = None, surface_material: str | None = None,
        import_fps: float = 30.0, _runner=None) -> dict:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("source must be a regular GLB file")
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 120:
        raise ValueError("fps must be an integer between 1 and 120")
    if (not isinstance(import_fps, (int, float)) or isinstance(import_fps, bool)
            or not math.isfinite(import_fps) or not 1 <= import_fps <= 240):
        raise ValueError("import fps must be finite and between 1 and 240")
    if not math.isfinite(duration) or not 0 < duration <= 60:
        raise ValueError("duration must be finite, positive and at most 60 seconds")
    if not math.isfinite(ortho_size) or ortho_size <= 0:
        raise ValueError("ortho size must be finite and positive")
    for name, values in (("camera center", camera_center), ("camera offset", camera_offset)):
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError(f"{name} needs three finite numbers")
    if math.hypot(camera_offset[0], camera_offset[2]) < 0.000001:
        raise ValueError("camera offset needs a nonzero horizontal component for a stable up direction")
    if not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    if rendering_method not in ("forward_plus", "gl_compatibility"):
        raise ValueError("rendering method must be forward_plus or gl_compatibility")
    if loop not in ("source", "linear", "ping-pong"):
        raise ValueError("loop must be source, linear or ping-pong")
    if measure_floor_y is not None:
        if not math.isfinite(measure_floor_y):
            raise ValueError("measurement floor Y must be finite")
        if animation is None:
            raise ValueError("floor measurement requires an animation")
    if surface_material is not None and measure_floor_y is None:
        raise ValueError("surface material requires --measure-floor-y")
    for name, value in (("animation", animation), ("player path", player_path),
                        ("follow bone", follow_bone), ("skeleton path", skeleton_path),
                        ("surface material", surface_material)):
        if value is not None and not value.strip():
            raise ValueError(f"{name} must not be empty")
    if skeleton_path and not follow_bone:
        raise ValueError("skeleton path requires a follow bone")
    digest = inspect_glb(source)
    command = godot or os.environ.get("GODOT_EXECUTABLE") or shutil.which("godot")
    if not command:
        raise ValueError("Godot was not found; use --godot or GODOT_EXECUTABLE")
    executable = Path(command).expanduser().resolve()
    if not executable.is_file():
        raise ValueError(f"Godot executable does not exist: {executable}")
    output = output.expanduser().absolute()
    if output.is_symlink() or output.exists():
        raise ValueError("output must be a fresh directory; existing paths are never overwritten")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / ".gdignore").touch()
    project = output / "project"
    project.mkdir()
    for name in ("project.godot", "main.gd", "main.tscn", "clearance.gd"):
        shutil.copyfile(PROJECT / name, project / name)
    shutil.copyfile(source, project / "source.glb")
    if hashlib.sha256((project / "source.glb").read_bytes()).hexdigest() != digest:
        raise RuntimeError("source changed while copying; run again into a fresh directory")
    request = {
        "source": str(source), "sourceSha256": digest,
        "animation": animation, "playerPath": player_path,
        "fps": fps, "importFps": import_fps, "durationSeconds": duration,
        "frameCount": max(1, math.ceil(duration * fps)),
        "orthoSize": ortho_size, "cameraCenter": list(camera_center),
        "cameraOffset": list(camera_offset), "followBone": follow_bone,
        "skeletonPath": skeleton_path, "output": str(output), "renderingMethod": rendering_method,
        "loop": loop,
        "measureFloorY": measure_floor_y, "surfaceMaterial": surface_material,
    }
    (project / "request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    arguments = [str(executable), "--path", str(project), "--audio-driver", "Dummy",
                 "--rendering-method", rendering_method]
    if animation is None:
        arguments.append("--headless")
    else:
        arguments.extend(["--resolution", f"{WIDTH}x{HEIGHT}", "--fixed-fps", str(fps)])
    runner = _runner or run_bounded
    try:
        result = runner(arguments, cwd=project, timeout_seconds=timeout, label="GLB motion preview")
    except TimeoutError as error:
        (output / "stderr.log").write_text(str(error) + "\n", encoding="utf-8")
        raise
    (output / "stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (output / "stderr.log").write_text(result.stderr or "", encoding="utf-8")
    record_path = output / "preview.json"
    if result.returncode != 0 or not record_path.is_file():
        raise RuntimeError(f"Godot preview failed (exit {result.returncode}); inspect {output}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("status") != "complete" or record.get("sourceSha256") != digest:
        raise RuntimeError(f"Godot preview record is incomplete or does not match the source: {record_path}")
    if (record.get("animationImportFps") != import_fps
            or isinstance(record.get("animationImportFps"), bool)):
        raise RuntimeError("Godot preview did not confirm the requested animation import rate")
    if animation is not None:
        frames = record.get("frames", [])
        if len(frames) != request["frameCount"]:
            raise RuntimeError("Godot preview emitted an unexpected frame count")
        for index, frame in enumerate(frames):
            name = f"frame-{index:05d}.png"
            if frame.get("file") != name or frame.get("dimensions") != [WIDTH, HEIGHT]:
                raise RuntimeError("Godot preview emitted an unexpected frame path or dimensions")
            with (output / name).open("rb") as stream:
                header = stream.read(24)
            if (len(header) != 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                    or struct.unpack(">II", header[16:24]) != (WIDTH, HEIGHT)):
                raise RuntimeError(f"invalid PNG or unexpected dimensions: {name}")
            # Godot reloads each saved PNG before recording this digest. A matching
            # header alone cannot establish that a capture survived intact.
            if hashlib.sha256((output / name).read_bytes()).hexdigest() != frame.get("sha256"):
                raise RuntimeError(f"PNG changed after native decoding: {name}")
            if measure_floor_y is not None:
                clearance = frame.get("clearance")
                if not isinstance(clearance, dict):
                    raise RuntimeError(f"missing or invalid native surface measurement: {name}")
                value = clearance.get("minimumY")
                count = clearance.get("referencedVertexCount")
                below = clearance.get("belowFloorVertexCount")
                if (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                        or not isinstance(count, int) or isinstance(count, bool) or count <= 0
                        or not isinstance(below, int) or isinstance(below, bool) or not 0 <= below <= count):
                    raise RuntimeError(f"missing or invalid native surface measurement: {name}")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="one self-contained GLB 2.0")
    parser.add_argument("--output", type=Path, required=True, help="fresh directory, normally in local-data/")
    parser.add_argument("--animation", help="exact imported clip name; omit to list clips without rendering")
    parser.add_argument("--loop", choices=("source", "linear", "ping-pong"), default="source",
                        help="preserve imported mode by default; explicit overrides affect preview only")
    parser.add_argument("--player-path", help="AnimationPlayer path relative to the imported GLB root")
    parser.add_argument("--fps", type=int, default=30, help="playback sampling and PNG output rate; default 30")
    parser.add_argument("--import-fps", type=float, default=30.0,
                        help="animation import bake rate (1–240 Hz), independent of capture FPS; default 30")
    parser.add_argument("--duration", type=float, default=4.0, help="output seconds (0 < duration <= 60); default 4")
    parser.add_argument("--ortho-size", type=float, default=3.5, help="orthographic vertical span in source units")
    parser.add_argument("--camera-center", type=vector, default=(0, 1, 0), help="fixed world target x,y,z; default 0,1,0")
    parser.add_argument("--camera-offset", type=vector, default=(4, 2, 6), help="camera offset from target x,y,z; default 4,2,6")
    parser.add_argument("--follow-bone", help="bone name; camera follows its displacement from frame zero")
    parser.add_argument("--skeleton-path", help="Skeleton3D path relative to GLB root if bone name is ambiguous")
    parser.add_argument("--measure-floor-y", type=float,
                        help="measure referenced surface vertices against this world Y plane; report only")
    parser.add_argument("--surface-material", help="measure only surfaces with this exact imported material name")
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--rendering-method", choices=("forward_plus", "gl_compatibility"),
                        default="forward_plus", help="default forward_plus; choose the consumer's renderer")
    parser.add_argument("--timeout", type=int, default=180, help="native process timeout seconds")
    args = parser.parse_args()
    try:
        record = run(args.source, args.output, animation=args.animation, player_path=args.player_path,
                     fps=args.fps, duration=args.duration, ortho_size=args.ortho_size,
                     camera_center=args.camera_center, camera_offset=args.camera_offset,
                     follow_bone=args.follow_bone, skeleton_path=args.skeleton_path,
                     godot=args.godot, timeout=args.timeout, rendering_method=args.rendering_method, loop=args.loop,
                     measure_floor_y=args.measure_floor_y, surface_material=args.surface_material,
                     import_fps=args.import_fps)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"motion preview: {error}\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
