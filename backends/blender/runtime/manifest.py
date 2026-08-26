from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.stage1_intake.probe_glb import _accessor_bounds, parse_glb


UPSTREAM_BASELINE = "d6673386f89673a58736f8d398dd16ece67874f5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _quaternion_from_euler_degrees(values: list[float]) -> list[float]:
    x, y, z = (math.radians(float(value)) / 2.0 for value in values)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    quaternion = [
        sx * cy * cz + cx * sy * sz,
        cx * sy * cz - sx * cy * sz,
        cx * cy * sz + sx * sy * cz,
        cx * cy * cz - sx * sy * sz,
    ]
    length = math.sqrt(sum(value * value for value in quaternion))
    return [0.0 if abs(value / length) < 1e-12 else value / length for value in quaternion]


def _transform(translation: list[float], rotation: list[float] | None = None) -> dict[str, Any]:
    return {
        "translation": [float(value) for value in translation],
        "rotationQuaternion": _quaternion_from_euler_degrees(rotation or [0.0, 0.0, 0.0]),
        "scale": [1.0, 1.0, 1.0],
    }


def _node_transform(node: dict[str, Any]) -> dict[str, Any]:
    if "matrix" in node:
        raise ValueError(f"GLB node {node.get('name')!r} unexpectedly uses a matrix transform")
    quaternion = [float(value) for value in node.get("rotation", [0.0, 0.0, 0.0, 1.0])]
    length = math.sqrt(sum(value * value for value in quaternion))
    if length == 0 or not math.isfinite(length):
        raise ValueError(f"GLB node {node.get('name')!r} has an invalid quaternion")
    return {
        "translation": [float(value) for value in node.get("translation", [0.0, 0.0, 0.0])],
        "rotationQuaternion": [value / length for value in quaternion],
        "scale": [float(value) for value in node.get("scale", [1.0, 1.0, 1.0])],
    }


def _triangle_count(document: dict[str, Any], primitive: dict[str, Any]) -> int:
    if int(primitive.get("mode", 4)) != 4:
        raise ValueError("only triangle-list glTF primitives are accepted")
    accessor_index = primitive.get("indices")
    if accessor_index is None:
        accessor_index = primitive.get("attributes", {}).get("POSITION")
    accessors = document.get("accessors", [])
    if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
        raise ValueError("mesh primitive has no valid index/POSITION accessor")
    count = int(accessors[accessor_index].get("count", 0))
    if count <= 0 or count % 3:
        raise ValueError("triangle-list accessor count must be a positive multiple of three")
    return count // 3


def _mesh_measurements(document: dict[str, Any], binary: bytes, mesh_index: int) -> tuple[int, dict[str, list[float]], list[int]]:
    mesh = document["meshes"][mesh_index]
    triangles = 0
    bounds: list[tuple[list[float], list[float]]] = []
    material_indices: list[int] = []
    for primitive in mesh["primitives"]:
        triangles += _triangle_count(document, primitive)
        position = primitive.get("attributes", {}).get("POSITION")
        minimum, maximum, warnings = _accessor_bounds(document, binary, int(position))
        if warnings:
            raise ValueError("; ".join(warnings))
        bounds.append((minimum, maximum))
        if isinstance(primitive.get("material"), int):
            material_indices.append(primitive["material"])
    return (
        triangles,
        {
            "min": [min(item[0][axis] for item in bounds) for axis in range(3)],
            "max": [max(item[1][axis] for item in bounds) for axis in range(3)],
        },
        sorted(set(material_indices)),
    )


def _close(left: list[float], right: list[float], tolerance: float = 1e-5) -> bool:
    return len(left) == len(right) and all(math.isclose(a, b, abs_tol=tolerance, rel_tol=tolerance) for a, b in zip(left, right))


def _same_transform(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not _close(actual["translation"], expected["translation"]) or not _close(actual["scale"], expected["scale"]):
        return False
    actual_rotation = actual["rotationQuaternion"]
    expected_rotation = expected["rotationQuaternion"]
    return _close(actual_rotation, expected_rotation) or _close(actual_rotation, [-value for value in expected_rotation])


def _metadata_nodes(document: dict[str, Any], graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = document.get("nodes", [])
    parents: dict[int, int] = {}
    for parent_index, parent in enumerate(nodes):
        for child_index in parent.get("children", []):
            parents[int(child_index)] = parent_index
    measured: dict[str, dict[str, Any]] = {}
    for node_index, node in enumerate(nodes):
        extras = node.get("extras", {}) if isinstance(node, dict) else {}
        kind = extras.get("assetforge_kind")
        asset_id = extras.get("assetforge_id")
        if kind not in {"pivot", "socket", "collision"}:
            continue
        if not isinstance(asset_id, str) or asset_id in measured:
            raise ValueError(f"GLB metadata node {node.get('name')!r} has invalid or duplicate assetforge_id")
        parent_index = parents.get(node_index)
        if parent_index is None:
            raise ValueError(f"GLB metadata node {asset_id!r} has no parent")
        parent_extras = nodes[parent_index].get("extras", {})
        parent_id = parent_extras.get("assetforge_id") or nodes[parent_index].get("name")
        measured[asset_id] = {
            "kind": kind,
            "gltfNodeIndex": node_index,
            "parentId": parent_id,
            "transform": _node_transform(node),
            "extras": extras,
        }

    contracts = {
        "pivot": graph["pivots"],
        "socket": graph["sockets"],
        "collision": graph["collisions"],
    }
    expected_ids = {value["id"] for values in contracts.values() for value in values}
    if set(measured) != expected_ids:
        raise ValueError(f"GLB metadata IDs differ from graph: measured={sorted(measured)} expected={sorted(expected_ids)}")
    for kind, values in contracts.items():
        for value in values:
            item = measured[value["id"]]
            parent_id = value.get("nodeId", value.get("parentNodeId"))
            expected_transform = _transform(value["translation"], value.get("rotationDegrees"))
            if item["kind"] != kind or item["parentId"] != parent_id:
                raise ValueError(f"GLB metadata relationship differs for {value['id']!r}")
            if not _same_transform(item["transform"], expected_transform):
                raise ValueError(f"GLB metadata transform differs for {value['id']!r}")
            extras = item["extras"]
            if kind == "pivot" and list(extras.get("axis", [])) != value["axis"]:
                raise ValueError(f"GLB pivot axis differs for {value['id']!r}")
            if kind == "socket" and list(extras.get("tags", [])) != value["tags"]:
                raise ValueError(f"GLB socket tags differ for {value['id']!r}")
            if kind == "collision":
                if list(extras.get("dimensions", [])) != value["dimensions"]:
                    raise ValueError(f"GLB collision dimensions differ for {value['id']!r}")
                if list(extras.get("layer_roles", [])) != value["layerRoles"]:
                    raise ValueError(f"GLB collision roles differ for {value['id']!r}")
    return measured


def _material_contracts(document: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    measured = {value.get("name"): value for value in document.get("materials", [])}
    result: list[dict[str, Any]] = []
    for expected in graph["materials"]:
        material = measured.get(expected["id"])
        if not isinstance(material, dict):
            raise ValueError(f"GLB is missing material {expected['id']!r}")
        pbr = material.get("pbrMetallicRoughness", {})
        base_color = [float(value) for value in pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])]
        metallic = float(pbr.get("metallicFactor", 1.0))
        roughness = float(pbr.get("roughnessFactor", 1.0))
        if not _close(base_color, expected["baseColorFactor"]) or not math.isclose(
            metallic, expected["metallicFactor"], abs_tol=1e-5
        ) or not math.isclose(roughness, expected["roughnessFactor"], abs_tol=1e-5):
            raise ValueError(f"GLB material parameters differ for {expected['id']!r}")
        result.append(
            {
                "id": expected["id"],
                "name": expected["name"],
                "model": "pbr-metallic-roughness",
                "baseColorFactor": base_color,
                "metallicFactor": metallic,
                "roughnessFactor": roughness,
                "doubleSided": bool(material.get("doubleSided", False)),
                "alphaMode": str(material.get("alphaMode", "OPAQUE")),
                "textureBindings": [],
            }
        )
    return result


def build_manifest(
    graph: dict[str, Any],
    glb_path: Path,
    builder_report: dict[str, Any],
    *,
    graph_path: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    document, binary, _ = parse_glb(glb_path)
    nodes = document.get("nodes", [])
    materials = document.get("materials", [])
    graph_order = {node["id"]: index for index, node in enumerate(graph["nodes"])}
    material_names = {index: material.get("name") for index, material in enumerate(materials)}
    mesh_nodes: list[dict[str, Any]] = []
    for node_index, node in enumerate(nodes):
        extras = node.get("extras", {}) if isinstance(node, dict) else {}
        if extras.get("assetforge_kind") != "render-mesh" or not isinstance(node.get("mesh"), int):
            continue
        source_id = extras.get("assetforge_source_component_id")
        lod_level = int(extras.get("assetforge_lod_level", -1))
        if source_id not in graph_order or lod_level not in (0, 1):
            raise ValueError(f"GLB render node {node.get('name')!r} has invalid provenance extras")
        manifest_id = source_id if lod_level == 0 else f"{source_id}-lod1"
        source_parent = graph["nodes"][graph_order[source_id]]["parentId"]
        parent_id = source_parent if lod_level == 0 or source_parent is None else f"{source_parent}-lod1"
        triangles, bounds, material_indices = _mesh_measurements(document, binary, node["mesh"])
        mesh_nodes.append(
            {
                "id": manifest_id,
                "name": node.get("name") or manifest_id,
                "sourceComponentId": source_id,
                "parentId": parent_id,
                "meshFile": glb_path.name,
                "gltfNodeIndex": node_index,
                "transform": _node_transform(node),
                "materialIds": [material_names[index] for index in material_indices],
                "lodLevel": lod_level,
                "triangleCount": triangles,
                "bounds": bounds,
            }
        )
    mesh_nodes.sort(key=lambda value: (value["lodLevel"], graph_order[value["sourceComponentId"]]))
    if len(mesh_nodes) != len(graph["nodes"]) * 2:
        raise ValueError("exported GLB does not contain exactly one LOD0 and one LOD1 mesh per source node")
    by_lod = {level: [value for value in mesh_nodes if value["lodLevel"] == level] for level in (0, 1)}
    lod_triangles = {level: sum(value["triangleCount"] for value in values) for level, values in by_lod.items()}
    if not 0 < lod_triangles[1] < lod_triangles[0]:
        raise ValueError(f"measured LOD triangle counts did not decrease: {lod_triangles}")
    for source_id in graph_order:
        near = next(value for value in by_lod[0] if value["sourceComponentId"] == source_id)
        far = next(value for value in by_lod[1] if value["sourceComponentId"] == source_id)
        if not 0 < far["triangleCount"] < near["triangleCount"]:
            raise ValueError(f"LOD1 did not reduce triangles for {source_id!r}")

    checked_at = _timestamp()
    material_contracts = _material_contracts(document, graph)
    metadata = _metadata_nodes(document, graph)
    lod_contract = graph["lods"][0]
    manifest = {
        "schemaVersion": "asset-manifest.v0",
        "generatedAt": checked_at,
        "asset": graph["asset"],
        "sourceSpecification": {**graph["sourceSpecification"], "referenceHashes": []},
        "generator": {
            "name": "img2threejs-godot constrained Blender backend",
            "version": "0.1.0",
            "backend": "blender",
            "upstreamRepository": "img2threejs/img2threejs",
            "upstreamBaselineSha": UPSTREAM_BASELINE,
            **provenance,
            "reproducibleBuildEpoch": int(os.environ["SOURCE_DATE_EPOCH"]) if os.environ.get("SOURCE_DATE_EPOCH") else None,
            "seed": 0,
            "toolVersions": {
                "blender": builder_report["blenderVersion"],
                "python": builder_report["pythonVersion"],
                "exporter": builder_report["exporter"],
            },
        },
        "coordinateSystem": {
            "unit": "meter",
            "metersPerUnit": 1.0,
            "handedness": "right",
            "forwardAxis": "+Z",
            "upAxis": "+Y",
        },
        "artifacts": [
            {"id": "asset-glb", "role": "glb", "path": glb_path.name, "sha256": _sha256(glb_path), "byteSize": glb_path.stat().st_size},
            {"id": "constructive-graph", "role": "constructive-graph", "path": graph_path.name, "sha256": _sha256(graph_path), "byteSize": graph_path.stat().st_size},
            {"id": "blender-stdout", "role": "process-log", "path": "blender.stdout.log", "sha256": _sha256(glb_path.parent / "blender.stdout.log"), "byteSize": (glb_path.parent / "blender.stdout.log").stat().st_size},
            {"id": "blender-stderr", "role": "process-log", "path": "blender.stderr.log", "sha256": _sha256(glb_path.parent / "blender.stderr.log"), "byteSize": (glb_path.parent / "blender.stderr.log").stat().st_size},
        ],
        "meshNodes": mesh_nodes,
        "materials": material_contracts,
        "textures": [],
        "lodLevels": [
            {
                "id": "lod0",
                "level": 0,
                "screenSizeThreshold": 1.0,
                "distanceMeters": 0.0,
                "meshNodeIds": [value["id"] for value in by_lod[0]],
                "triangleCount": lod_triangles[0],
            },
            {
                "id": lod_contract["id"],
                "level": 1,
                "screenSizeThreshold": float(lod_contract["screenSizeThreshold"]),
                "distanceMeters": float(lod_contract["distanceMeters"]),
                "meshNodeIds": [value["id"] for value in by_lod[1]],
                "triangleCount": lod_triangles[1],
            },
        ],
        "collisionShapes": [
            {
                "id": value["id"],
                "nodeId": value["nodeId"],
                "type": value["type"],
                "transform": metadata[value["id"]]["transform"],
                "gltfNodeIndex": metadata[value["id"]]["gltfNodeIndex"],
                "dimensions": value["dimensions"],
                "isTrigger": value["isTrigger"],
                "layerRoles": value["layerRoles"],
            }
            for value in graph["collisions"]
        ],
        "pivots": [
            {"id": value["id"], "nodeId": value["nodeId"], "purpose": value["purpose"], "transform": metadata[value["id"]]["transform"], "gltfNodeIndex": metadata[value["id"]]["gltfNodeIndex"]}
            for value in graph["pivots"]
        ],
        "sockets": [
            {
                "id": value["id"],
                "parentNodeId": value["parentNodeId"],
                "purpose": value["purpose"],
                "transform": metadata[value["id"]]["transform"],
                "gltfNodeIndex": metadata[value["id"]]["gltfNodeIndex"],
                "tags": value["tags"],
            }
            for value in graph["sockets"]
        ],
        "animationHooks": [
            {"id": "turret-yaw", "nodeId": graph["pivots"][0]["nodeId"], "kind": "rotation", "channel": "rotation:y", "axis": graph["pivots"][0]["axis"]}
        ],
        "vfxAnchors": [{"id": "muzzle-vfx-anchor", "socketId": "muzzle-vfx", "role": "muzzle-vfx", "orientationPolicy": "socket-local"}],
        "destructionGroups": [],
        "navigationMetadata": {
            "staticObstacle": False,
            "walkable": False,
            "carveNavigation": False,
            "avoidanceRadiusMeters": 1.6,
            "layerRoles": ["vehicle"],
            "footprintNodeIds": ["hull"],
        },
        "statistics": {
            "triangleCount": sum(lod_triangles.values()),
            "meshCount": len(mesh_nodes),
            "materialCount": len(material_contracts),
            "textureCount": 0,
            "drawCallEstimate": len(mesh_nodes),
            "textureResolutions": [],
        },
        "licenseAndProvenance": {
            "outputLicense": "Apache-2.0",
            "upstreamLicense": "Apache-2.0",
            "notices": [
                "Generic procedural benchmark; no game assets or private references were used.",
                "The Blender-executed builder is GPL-3.0-or-later; generated data retains the output license recorded here.",
            ],
            "sources": [
                {
                    "type": "specification",
                    "identifier": graph["sourceSpecification"]["path"],
                    "license": "Apache-2.0",
                    "sha256": graph["sourceSpecification"]["sha256"],
                },
                {
                    "type": "generator",
                    "identifier": "img2threejs/img2threejs",
                    "uri": "https://github.com/img2threejs/img2threejs",
                    "license": "Apache-2.0",
                },
                {
                    "type": "generator",
                    "identifier": "backends/blender/runtime/blender_build.py",
                    "uri": "https://github.com/dlprentice/img2threejs-godot",
                    "license": "GPL-3.0-or-later",
                    "sha256": _sha256(Path(__file__).with_name("blender_build.py")),
                },
            ],
        },
        "validationResults": [
            {
                "id": "glb-structure",
                "validator": "assetforge stdlib GLB parser",
                "validatorVersion": "0.1.0",
                "status": "pass",
                "checkedAt": checked_at,
                "messages": [
                    {"code": "lod-reduced", "severity": "info", "text": f"Measured triangles decreased from {lod_triangles[0]} to {lod_triangles[1]}."}
                ],
                "artifactIds": ["asset-glb", "constructive-graph"],
            }
        ],
        "visualReviewResults": [],
        "retryHistory": [],
    }
    return manifest
