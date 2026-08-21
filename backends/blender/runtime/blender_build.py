# SPDX-License-Identifier: GPL-3.0-or-later
"""Trusted Blender entry point for the constrained constructive graph.

This file is executed by Blender, so its license is GPL-compatible. It never
evaluates code from the input graph and accepts only the operations validated
by ``graph.py``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backends.blender.runtime.graph import load_graph  # noqa: E402


CANONICAL_TO_BLENDER = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))


def _arguments() -> argparse.Namespace:
    separator = sys.argv.index("--") if "--" in sys.argv else len(sys.argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(sys.argv[separator + 1 :])


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


def _vector(values: list[float]) -> tuple[float, float, float]:
    result = CANONICAL_TO_BLENDER @ Vector(tuple(float(value) for value in values))
    return tuple(float(result[index]) for index in range(3))


def _rotation(values: list[float]):
    canonical = Euler(tuple(math.radians(float(value)) for value in values), "XYZ").to_matrix()
    converted = CANONICAL_TO_BLENDER @ canonical @ CANONICAL_TO_BLENDER.transposed()
    return converted.to_quaternion().normalized()


def _mesh_from_canonical(name: str, vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]]):
    mesh = bpy.data.meshes.new(f"{name}__mesh")
    mesh.from_pydata([_vector(list(vertex)) for vertex in vertices], [], faces)
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    return mesh


def _box_mesh(name: str, size: list[float], mirrored: bool):
    half_x, half_y, half_z = (float(value) / 2.0 for value in size)
    minimum_x = 0.0 if mirrored else -half_x
    vertices = [
        (minimum_x, -half_y, -half_z),
        (half_x, -half_y, -half_z),
        (half_x, half_y, -half_z),
        (minimum_x, half_y, -half_z),
        (minimum_x, -half_y, half_z),
        (half_x, -half_y, half_z),
        (half_x, half_y, half_z),
        (minimum_x, half_y, half_z),
    ]
    faces = [(3, 2, 1, 0), (5, 6, 7, 4), (1, 5, 4, 0), (2, 6, 5, 1), (3, 7, 6, 2)]
    if not mirrored:
        faces.append((7, 3, 0, 4))
    return _mesh_from_canonical(name, vertices, faces)


def _cylinder_mesh(name: str, radius: float, depth: float, vertices_count: int):
    vertices: list[tuple[float, float, float]] = []
    for z in (0.0, float(depth)):
        for index in range(vertices_count):
            angle = 2.0 * math.pi * index / vertices_count
            vertices.append((radius * math.cos(angle), radius * math.sin(angle), z))
    bottom_center = len(vertices)
    top_center = bottom_center + 1
    vertices.extend([(0.0, 0.0, 0.0), (0.0, 0.0, float(depth))])
    faces: list[tuple[int, ...]] = []
    for index in range(vertices_count):
        following = (index + 1) % vertices_count
        faces.append((index, following, vertices_count + following, vertices_count + index))
        faces.append((bottom_center, following, index))
        faces.append((top_center, vertices_count + index, vertices_count + following))
    return _mesh_from_canonical(name, vertices, faces)


def _active(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _apply_modifiers(obj, modifiers: list[dict]) -> None:
    for index, contract in enumerate(modifiers):
        operation = contract["operation"]
        if operation == "mirror":
            modifier = obj.modifiers.new(name=f"{index:02d}_mirror", type="MIRROR")
            modifier.use_axis = (contract["axis"] == "X", contract["axis"] == "Z", contract["axis"] == "Y")
            modifier.use_clip = True
            modifier.use_mirror_merge = True
        elif operation == "bevel":
            modifier = obj.modifiers.new(name=f"{index:02d}_bevel", type="BEVEL")
            modifier.width = float(contract["width"])
            modifier.segments = int(contract["segments"])
            modifier.limit_method = "ANGLE"
        else:  # The outer graph validator makes this unreachable.
            raise ValueError(f"unsupported modifier {operation!r}")
        _active(obj)
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def _verify_closed_outward(obj) -> None:
    mesh = obj.data
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    edge_counts: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        for edge in polygon.edge_keys:
            edge_counts[tuple(sorted(edge))] += 1
    invalid_edges = sum(1 for count in edge_counts.values() if count != 2)
    if invalid_edges:
        raise ValueError(f"{obj.name!r} is not closed: {invalid_edges} edges do not have exactly two incident faces")
    coordinates = [vertex.co for vertex in mesh.vertices]
    minimum = Vector(tuple(min(value[axis] for value in coordinates) for axis in range(3)))
    maximum = Vector(tuple(max(value[axis] for value in coordinates) for axis in range(3)))
    center = (minimum + maximum) / 2.0
    inward = [polygon.index for polygon in mesh.polygons if (polygon.center - center).dot(polygon.normal) < -1e-6]
    if inward:
        raise ValueError(f"{obj.name!r} has {len(inward)} inward-facing polygons")
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:
        raise ValueError(f"{obj.name!r} contains no triangles")


def _material(contract: dict):
    material = bpy.data.materials.new(contract["id"])
    material.diffuse_color = tuple(contract["baseColorFactor"])
    material.metallic = float(contract["metallicFactor"])
    material.roughness = float(contract["roughnessFactor"])
    material.use_backface_culling = True
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = tuple(contract["baseColorFactor"])
    principled.inputs["Metallic"].default_value = float(contract["metallicFactor"])
    principled.inputs["Roughness"].default_value = float(contract["roughnessFactor"])
    return material


def _new_object(node: dict, material, collection):
    modifiers = node["modifiers"]
    if node["operation"] == "rounded_box":
        mirrored = any(item["operation"] == "mirror" for item in modifiers)
        mesh = _box_mesh(node["id"], node["size"], mirrored)
    elif node["operation"] == "cylinder":
        if node["axis"] != "Z" or not node["originAtStart"]:
            raise ValueError("the initial Blender proof supports only +Z cylinders with originAtStart")
        mesh = _cylinder_mesh(node["id"], float(node["radius"]), float(node["depth"]), int(node["vertices"]))
    else:
        raise ValueError(f"unsupported operation {node['operation']!r}")
    obj = bpy.data.objects.new(node["id"], mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.location = _vector(node["transform"]["translation"])
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = _rotation(node["transform"]["rotationDegrees"])
    obj.scale = (1.0, 1.0, 1.0)
    obj["assetforge_id"] = node["id"]
    obj["assetforge_source_component_id"] = node["sourceComponentId"]
    obj["assetforge_lod_level"] = 0
    obj["assetforge_kind"] = "render-mesh"
    _apply_modifiers(obj, modifiers)
    _verify_closed_outward(obj)
    return obj


def _lod_object(source, node: dict, collection, ratio: float):
    lod_id = f"{node['id']}-lod1"
    obj = source.copy()
    obj.data = source.data.copy()
    obj.name = lod_id
    obj.data.name = f"{lod_id}__mesh"
    collection.objects.link(obj)
    obj["assetforge_id"] = lod_id
    obj["assetforge_source_component_id"] = node["sourceComponentId"]
    obj["assetforge_lod_level"] = 1
    modifier = obj.modifiers.new(name="00_decimate", type="DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = float(ratio)
    modifier.use_collapse_triangulate = True
    _active(obj)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    _verify_closed_outward(obj)
    return obj


def _empty(name: str, location: list[float], *, display: str, size: float, collection, properties: dict):
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.empty_display_type = display
    obj.empty_display_size = size
    obj.location = _vector(location)
    for key, value in properties.items():
        obj[key] = value
    return obj


def build(graph: dict, output: Path) -> dict:
    started = time.perf_counter()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.context.scene.unit_settings.length_unit = "METERS"

    root = bpy.context.scene.collection
    lod0_collection = bpy.data.collections.new("Render_LOD0")
    lod1_collection = bpy.data.collections.new("Render_LOD1")
    rig_collection = bpy.data.collections.new("Rig_Metadata")
    collision_collection = bpy.data.collections.new("Collision_Metadata")
    for collection in (lod0_collection, lod1_collection, rig_collection, collision_collection):
        root.children.link(collection)

    materials = {contract["id"]: _material(contract) for contract in graph["materials"]}
    lod0: dict[str, object] = {}
    for node in graph["nodes"]:
        obj = _new_object(node, materials[node["materialId"]], lod0_collection)
        if node["parentId"] is not None:
            obj.parent = lod0[node["parentId"]]
        lod0[node["id"]] = obj

    lod_contract = graph["lods"][0]
    lod1: dict[str, object] = {}
    for node in graph["nodes"]:
        obj = _lod_object(lod0[node["id"]], node, lod1_collection, float(lod_contract["targetRatio"]))
        obj.parent = None
        if node["parentId"] is not None:
            obj.parent = lod1[node["parentId"]]
        lod1[node["id"]] = obj

    for pivot in graph["pivots"]:
        obj = _empty(
            pivot["id"],
            pivot["translation"],
            display="CIRCLE",
            size=0.35,
            collection=rig_collection,
            properties={"assetforge_id": pivot["id"], "assetforge_kind": "pivot", "axis": pivot["axis"]},
        )
        obj.parent = lod0[pivot["nodeId"]]
    for socket in graph["sockets"]:
        obj = _empty(
            socket["id"],
            socket["translation"],
            display="ARROWS",
            size=0.25,
            collection=rig_collection,
            properties={"assetforge_id": socket["id"], "assetforge_kind": "socket", "tags": socket["tags"]},
        )
        obj.parent = lod0[socket["parentNodeId"]]
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = _rotation(socket["rotationDegrees"])
    for collision in graph["collisions"]:
        obj = _empty(
            collision["id"],
            collision["translation"],
            display="CUBE",
            size=1.0,
            collection=collision_collection,
            properties={
                "assetforge_id": collision["id"],
                "assetforge_kind": "collision",
                "dimensions": collision["dimensions"],
                "layer_roles": collision["layerRoles"],
            },
        )
        obj.parent = lod0[collision["nodeId"]]
        obj.empty_display_size = max(float(value) for value in collision["dimensions"]) / 2.0

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.stem}.{os.getpid()}.glb"
    temporary.unlink(missing_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(temporary),
        check_existing=False,
        export_format="GLB",
        export_yup=True,
        export_extras=True,
        export_cameras=False,
        export_lights=False,
        export_apply=False,
    )
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise RuntimeError("Blender exporter did not create a non-empty GLB")
    os.replace(temporary, output)
    return {
        "status": "pass",
        "blenderVersion": bpy.app.version_string,
        "pythonVersion": sys.version.split()[0],
        "exporter": "Blender glTF 2.0 exporter",
        "meshObjectCount": len(lod0) + len(lod1),
        "emptyObjectCount": len(graph["pivots"]) + len(graph["sockets"]) + len(graph["collisions"]),
        "durationSeconds": round(time.perf_counter() - started, 6),
        "warnings": [],
    }


def main() -> int:
    args = _arguments()
    try:
        graph = load_graph(args.graph.resolve())
        report = build(graph, args.output.resolve())
        _write_json_atomic(args.report.resolve(), report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - Blender boundary must record all failures.
        report = {"status": "fail", "error": str(exc), "traceback": traceback.format_exc()}
        _write_json_atomic(args.report.resolve(), report)
        print(json.dumps(report, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
