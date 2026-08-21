from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from forge.stage2_spec.validate_sculpt_spec import validate_spec

from .graph import validate_graph


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hex_factor(value: str) -> list[float]:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"unsupported material color {value!r}")
    return [int(value[index : index + 2], 16) / 255.0 for index in (1, 3, 5)] + [1.0]


def _radians_to_degrees(values: list[float]) -> list[float]:
    return [math.degrees(float(value)) for value in values]


def _component_transform(component: dict[str, Any]) -> dict[str, list[float]]:
    source = component.get("transform")
    if not isinstance(source, dict):
        raise ValueError(f"component {component.get('id')!r} has no transform")
    scale = [float(value) for value in source.get("scale", [])]
    if scale != [1.0, 1.0, 1.0]:
        raise ValueError(f"component {component.get('id')!r} must bake dimensions and use identity transform scale")
    return {
        "translation": [float(value) for value in source["position"]],
        "rotationDegrees": _radians_to_degrees(source["rotation"]),
        "scale": scale,
    }


def _bevel(component: dict[str, Any]) -> dict[str, Any] | None:
    descriptor = component.get("geometryDescriptor")
    edge = descriptor.get("edgeTreatment") if isinstance(descriptor, dict) else None
    if not isinstance(edge, dict) or float(edge.get("bevelRadius", 0.0)) <= 0:
        return None
    return {
        "operation": "bevel",
        "width": float(edge["bevelRadius"]),
        "segments": int(edge.get("segments", 1)),
    }


def _modifiers(component: dict[str, Any]) -> list[dict[str, Any]]:
    modifiers: list[dict[str, Any]] = []
    descriptor = component.get("geometryDescriptor")
    stack = descriptor.get("deformationStack") if isinstance(descriptor, dict) else []
    if isinstance(stack, list):
        for operation in stack:
            if isinstance(operation, dict) and operation.get("operation") == "mirror":
                modifiers.append({"operation": "mirror", "axis": operation.get("axis")})
    bevel = _bevel(component)
    if bevel:
        modifiers.append(bevel)
    return modifiers


def adapt_object_sculpt_spec(spec_path: Path, *, reject_warnings: bool = True) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("ObjectSculptSpec must be an object")
    errors, warnings = validate_spec(spec)
    if errors or (reject_warnings and warnings):
        messages = [f"error: {message}" for message in errors] + [f"warning: {message}" for message in warnings]
        raise ValueError("ObjectSculptSpec failed validation:\n- " + "\n- ".join(messages))

    components = spec["componentTree"]
    component_by_id = {component["id"]: component for component in components}
    if set(component_by_id) != {"hull", "turret", "weapon"}:
        raise ValueError("proof adapter requires exactly hull, turret, and weapon components")
    materials = spec["materials"]
    if len(materials) != 1 or materials[0].get("id") != "painted-metal":
        raise ValueError("proof adapter requires exactly one painted-metal material")

    graph_nodes: list[dict[str, Any]] = []
    for component_id in ("hull", "turret"):
        component = component_by_id[component_id]
        dimensions = component["dimensions"]
        graph_nodes.append(
            {
                "id": component_id,
                "name": component["name"],
                "sourceComponentId": component_id,
                "parentId": component["parent"],
                "operation": "rounded_box",
                "transform": _component_transform(component),
                "materialId": component["material"],
                "size": [float(dimensions["width"]), float(dimensions["height"]), float(dimensions["depth"])],
                "modifiers": _modifiers(component),
            }
        )

    weapon = component_by_id["weapon"]
    attachment = weapon.get("attachment")
    if not isinstance(attachment, dict):
        raise ValueError("weapon requires an attachment contract")
    start = [float(value) for value in attachment["localStart"]]
    end = [float(value) for value in attachment["localEnd"]]
    delta = [end[index] - start[index] for index in range(3)]
    depth = math.sqrt(sum(value * value for value in delta))
    if delta != [0.0, 0.0, depth]:
        raise ValueError("initial cylinder adapter supports only a +Z source-space weapon")
    if float(attachment["baseRadius"]) != float(attachment["endRadius"]):
        raise ValueError("cylinder adapter cannot discard a tapered attachment")
    graph_nodes.append(
        {
            "id": "weapon",
            "name": weapon["name"],
            "sourceComponentId": "weapon",
            "parentId": "turret",
            "operation": "cylinder",
            "transform": {
                "translation": start,
                "rotationDegrees": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            "materialId": weapon["material"],
            "radius": float(attachment["baseRadius"]),
            "depth": depth,
            "vertices": 32,
            "axis": "Z",
            "originAtStart": True,
            "modifiers": [modifier for modifier in _modifiers(weapon) if modifier["operation"] == "bevel"],
        }
    )

    turret_profile = component_by_id["turret"]["actionProfile"]
    pivot = turret_profile["pivot"]
    source_sockets = [
        ("turret", turret_profile["sockets"][0], "primary weapon attachment", ["weapon"]),
        ("weapon", weapon["actionProfile"]["sockets"][0], "muzzle VFX attachment", ["muzzle", "vfx"]),
    ]
    hull_collider = component_by_id["hull"]["actionProfile"]["collider"]
    far_lod = next(item for item in spec["lodPlan"] if item["tier"] == "far")
    material = materials[0]
    graph = {
        "schemaVersion": 1,
        "asset": {"id": spec["targetId"], "version": "0.1.0", "displayName": spec["targetName"]},
        "sourceSpecification": {
            "path": spec_path.name,
            "sha256": _sha256(spec_path),
            "schemaVersion": str(spec["schemaVersion"]),
        },
        "coordinateSystem": {"unit": "meter", "handedness": "right", "forwardAxis": [0, 0, 1], "upAxis": [0, 1, 0]},
        "materials": [
            {
                "id": material["id"],
                "name": material["name"],
                "baseColorFactor": _hex_factor(material["baseColor"]),
                "metallicFactor": float(material["metalness"]["base"]),
                "roughnessFactor": float(material["roughness"]["base"]),
            }
        ],
        "nodes": graph_nodes,
        "pivots": [
            {
                "id": "turret-pivot",
                "nodeId": "turret",
                "purpose": "rotation",
                "translation": [float(value) for value in pivot["localPosition"]],
                "axis": [float(value) for value in pivot["axis"]],
            }
        ],
        "sockets": [
            {
                "id": socket["id"],
                "parentNodeId": parent_id,
                "purpose": purpose,
                "translation": [float(value) for value in socket["localPosition"]],
                "rotationDegrees": _radians_to_degrees(socket["localRotation"]),
                "tags": tags,
            }
            for parent_id, socket, purpose, tags in source_sockets
        ],
        "collisions": [
            {
                "id": "hull-collision",
                "nodeId": "hull",
                "type": "box",
                "translation": [float(value) for value in hull_collider["offset"]],
                "dimensions": [float(value) for value in hull_collider["scale"]],
                "isTrigger": False,
                "layerRoles": ["vehicle", "world"],
            }
        ],
        "lods": [
            {
                "id": "vehicle-lod1",
                "level": 1,
                "distanceMeters": float(far_lod["distance"]),
                "targetRatio": float(far_lod["targetRatio"]),
                "sourceNodeIds": list(far_lod["componentRefs"]),
            }
        ],
    }
    graph_errors = validate_graph(graph)
    if graph_errors:
        raise ValueError("adapter emitted an invalid graph:\n- " + "\n- ".join(graph_errors))
    return graph
