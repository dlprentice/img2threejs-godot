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
    value = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


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


def build_manifest(graph: dict[str, Any], glb_path: Path, builder_report: dict[str, Any]) -> dict[str, Any]:
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
    material_contracts = [
        {
            "id": value["id"],
            "name": value["name"],
            "model": "pbr-metallic-roughness",
            "baseColorFactor": value["baseColorFactor"],
            "metallicFactor": value["metallicFactor"],
            "roughnessFactor": value["roughnessFactor"],
            "doubleSided": False,
            "alphaMode": "OPAQUE",
            "textureBindings": [],
        }
        for value in graph["materials"]
    ]
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
            {"id": "asset-glb", "role": "glb", "path": glb_path.name, "sha256": _sha256(glb_path), "byteSize": glb_path.stat().st_size}
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
                "screenSizeThreshold": float(lod_contract["targetRatio"]),
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
                "transform": _transform(value["translation"]),
                "dimensions": value["dimensions"],
                "isTrigger": value["isTrigger"],
                "layerRoles": value["layerRoles"],
            }
            for value in graph["collisions"]
        ],
        "pivots": [
            {"id": value["id"], "nodeId": value["nodeId"], "purpose": value["purpose"], "transform": _transform(value["translation"])}
            for value in graph["pivots"]
        ],
        "sockets": [
            {
                "id": value["id"],
                "parentNodeId": value["parentNodeId"],
                "purpose": value["purpose"],
                "transform": _transform(value["translation"], value["rotationDegrees"]),
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
            "notices": ["Generic procedural benchmark; no game assets or private references were used."],
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
                "artifactIds": ["asset-glb"],
            }
        ],
        "visualReviewResults": [],
        "retryHistory": [],
    }
    return manifest
