from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "asset",
    "sourceSpecification",
    "coordinateSystem",
    "materials",
    "nodes",
    "pivots",
    "sockets",
    "collisions",
    "lods",
}
NODE_FIELDS = {
    "id",
    "name",
    "sourceComponentId",
    "parentId",
    "operation",
    "transform",
    "materialId",
    "size",
    "radius",
    "depth",
    "vertices",
    "axis",
    "originAtStart",
    "modifiers",
}


def load_graph(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("constructive graph must be a JSON object")
    errors = validate_graph(payload)
    if errors:
        raise ValueError("invalid constructive graph:\n- " + "\n- ".join(errors))
    return payload


def _exact_fields(value: Any, allowed: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    unknown = sorted(set(value) - allowed)
    if unknown:
        errors.append(f"{label} has unknown fields: {', '.join(unknown)}")
    return True


def _id(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        errors.append(f"{label} must match {ID_PATTERN.pattern}")
        return False
    return True


def _vec3(value: Any, label: str, errors: list[str], *, positive: bool = False) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        errors.append(f"{label} must be a three-number array")
        return False
    valid = True
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            valid = False
        elif positive and float(item) <= 0:
            valid = False
    if not valid:
        errors.append(f"{label} must contain {'positive ' if positive else ''}finite numbers")
    return valid


def _transform(value: Any, label: str, errors: list[str]) -> None:
    fields = {"translation", "rotationDegrees", "scale"}
    if not _exact_fields(value, fields, label, errors):
        return
    missing = sorted(fields - set(value))
    if missing:
        errors.append(f"{label} is missing: {', '.join(missing)}")
        return
    _vec3(value["translation"], f"{label}.translation", errors)
    _vec3(value["rotationDegrees"], f"{label}.rotationDegrees", errors)
    _vec3(value["scale"], f"{label}.scale", errors, positive=True)
    if value.get("scale") != [1, 1, 1]:
        errors.append(f"{label}.scale must be identity because dimensions are baked")


def _finite_number(
    value: Any,
    label: str,
    errors: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        errors.append(f"{label} must be a finite number")
        return False
    number = float(value)
    if minimum is not None and (number <= minimum if exclusive_minimum else number < minimum):
        operator = ">" if exclusive_minimum else ">="
        errors.append(f"{label} must be {operator} {minimum}")
        return False
    if maximum is not None and number > maximum:
        errors.append(f"{label} must be <= {maximum}")
        return False
    return True


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _exact_fields(graph, TOP_LEVEL_FIELDS, "graph", errors)
    missing = sorted(TOP_LEVEL_FIELDS - set(graph))
    if missing:
        errors.append(f"graph is missing: {', '.join(missing)}")
        return errors
    if graph.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    asset = graph.get("asset")
    if _exact_fields(asset, {"id", "version", "displayName"}, "asset", errors):
        _id(asset.get("id"), "asset.id", errors)
        for field in ("version", "displayName"):
            if not isinstance(asset.get(field), str) or not asset[field]:
                errors.append(f"asset.{field} must be a non-empty string")

    source = graph.get("sourceSpecification")
    if _exact_fields(source, {"path", "sha256", "schemaVersion"}, "sourceSpecification", errors):
        if not isinstance(source.get("path"), str) or not source["path"]:
            errors.append("sourceSpecification.path must be a non-empty string")
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            errors.append("sourceSpecification.sha256 must be lowercase SHA-256")

    coordinate = graph.get("coordinateSystem")
    expected_coordinate = {"unit": "meter", "handedness": "right", "forwardAxis": [0, 0, 1], "upAxis": [0, 1, 0]}
    if coordinate != expected_coordinate:
        errors.append("coordinateSystem must be right-handed meters with +Z forward and +Y up")

    materials = graph.get("materials")
    material_ids: set[str] = set()
    if not isinstance(materials, list) or not materials:
        errors.append("materials must be a non-empty array")
    else:
        for index, material in enumerate(materials):
            label = f"materials[{index}]"
            fields = {"id", "name", "baseColorFactor", "metallicFactor", "roughnessFactor"}
            if not _exact_fields(material, fields, label, errors):
                continue
            material_id = material.get("id")
            if _id(material_id, f"{label}.id", errors):
                if material_id in material_ids:
                    errors.append(f"duplicate material id {material_id!r}")
                material_ids.add(material_id)
            color = material.get("baseColorFactor")
            if not isinstance(color, list) or len(color) != 4 or any(
                isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1 for item in color
            ):
                errors.append(f"{label}.baseColorFactor must contain four values in [0, 1]")
            for field in ("metallicFactor", "roughnessFactor"):
                _finite_number(material.get(field), f"{label}.{field}", errors, minimum=0, maximum=1)

    nodes = graph.get("nodes")
    node_ids: set[str] = set()
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty array")
    else:
        for index, node in enumerate(nodes):
            label = f"nodes[{index}]"
            if not isinstance(node, dict):
                errors.append(f"{label} must be an object")
                continue
            unknown = sorted(set(node) - NODE_FIELDS)
            if unknown:
                errors.append(f"{label} has unknown fields: {', '.join(unknown)}")
            required = {"id", "name", "sourceComponentId", "parentId", "operation", "transform", "materialId", "modifiers"}
            missing_node = sorted(required - set(node))
            if missing_node:
                errors.append(f"{label} is missing: {', '.join(missing_node)}")
                continue
            node_id = node.get("id")
            if _id(node_id, f"{label}.id", errors):
                if node_id in node_ids:
                    errors.append(f"duplicate node id {node_id!r}")
                node_ids.add(node_id)
            _id(node.get("sourceComponentId"), f"{label}.sourceComponentId", errors)
            parent = node.get("parentId")
            if parent is not None and (not isinstance(parent, str) or parent not in node_ids):
                errors.append(f"{label}.parentId must reference an earlier node")
            if node.get("materialId") not in material_ids:
                errors.append(f"{label}.materialId references an unknown material")
            _transform(node.get("transform"), f"{label}.transform", errors)
            operation = node.get("operation")
            if operation == "rounded_box":
                _vec3(node.get("size"), f"{label}.size", errors, positive=True)
                forbidden = {"radius", "depth", "vertices", "axis", "originAtStart"} & set(node)
                if forbidden:
                    errors.append(f"{label} rounded_box has cylinder fields: {', '.join(sorted(forbidden))}")
            elif operation == "cylinder":
                for field in ("radius", "depth"):
                    _finite_number(node.get(field), f"{label}.{field}", errors, minimum=0, exclusive_minimum=True)
                if not isinstance(node.get("vertices"), int) or not 8 <= node["vertices"] <= 64:
                    errors.append(f"{label}.vertices must be an integer from 8 to 64")
                if node.get("axis") not in {"X", "-X", "Y", "-Y", "Z", "-Z"}:
                    errors.append(f"{label}.axis is unsupported")
                if not isinstance(node.get("originAtStart"), bool):
                    errors.append(f"{label}.originAtStart must be boolean")
                if "size" in node:
                    errors.append(f"{label} cylinder cannot have size")
            else:
                errors.append(f"{label}.operation is unsupported")
            modifiers = node.get("modifiers")
            if not isinstance(modifiers, list):
                errors.append(f"{label}.modifiers must be an array")
            else:
                seen_modifiers: set[str] = set()
                modifier_order: list[str] = []
                for modifier_index, modifier in enumerate(modifiers):
                    modifier_label = f"{label}.modifiers[{modifier_index}]"
                    if not isinstance(modifier, dict):
                        errors.append(f"{modifier_label} must be an object")
                        continue
                    kind = modifier.get("operation")
                    modifier_order.append(str(kind))
                    if kind in seen_modifiers:
                        errors.append(f"{label} repeats modifier {kind!r}")
                    seen_modifiers.add(str(kind))
                    if kind == "bevel":
                        _exact_fields(modifier, {"operation", "width", "segments"}, modifier_label, errors)
                        if not isinstance(modifier.get("segments"), int) or not 1 <= modifier["segments"] <= 6:
                            errors.append(f"{modifier_label}.segments must be from 1 to 6")
                        _finite_number(modifier.get("width"), f"{modifier_label}.width", errors, minimum=0, maximum=1)
                    elif kind == "mirror" and operation == "rounded_box":
                        _exact_fields(modifier, {"operation", "axis"}, modifier_label, errors)
                        if modifier.get("axis") not in {"X", "Y", "Z"}:
                            errors.append(f"{modifier_label}.axis is unsupported")
                    else:
                        errors.append(f"{modifier_label}.operation is unsupported for {operation}")
                if modifier_order != sorted(modifier_order, key={"mirror": 0, "bevel": 1}.get):
                    errors.append(f"{label}.modifiers must be ordered mirror then bevel")

        roots = [node for node in nodes if isinstance(node, dict) and node.get("parentId") is None]
        if len(roots) != 1:
            errors.append("nodes must contain exactly one root")

    _validate_relationships(graph, node_ids, errors)
    return errors


def _validate_relationships(graph: dict[str, Any], node_ids: set[str], errors: list[str]) -> None:
    definitions = (
        ("pivots", {"id", "nodeId", "purpose", "translation", "axis"}),
        ("sockets", {"id", "parentNodeId", "purpose", "translation", "rotationDegrees", "tags"}),
        ("collisions", {"id", "nodeId", "type", "translation", "dimensions", "isTrigger", "layerRoles"}),
        ("lods", {"id", "level", "distanceMeters", "targetRatio", "sourceNodeIds"}),
    )
    material_ids = {
        value.get("id")
        for value in graph.get("materials", [])
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    }
    overlapping = sorted(node_ids & material_ids)
    for value_id in overlapping:
        errors.append(f"duplicate graph id {value_id!r}")
    all_ids: set[str] = set(node_ids) | material_ids
    for collection_name, fields in definitions:
        values = graph.get(collection_name)
        if not isinstance(values, list):
            errors.append(f"{collection_name} must be an array")
            continue
        for index, value in enumerate(values):
            label = f"{collection_name}[{index}]"
            if not _exact_fields(value, fields, label, errors):
                continue
            missing = sorted(fields - set(value))
            if missing:
                errors.append(f"{label} is missing: {', '.join(missing)}")
                continue
            value_id = value.get("id")
            if _id(value_id, f"{label}.id", errors):
                if value_id in all_ids:
                    errors.append(f"duplicate graph id {value_id!r}")
                all_ids.add(value_id)
            node_reference = value.get("nodeId", value.get("parentNodeId"))
            if node_reference is not None and node_reference not in node_ids:
                errors.append(f"{label} references unknown node {node_reference!r}")
            if collection_name == "pivots":
                _vec3(value.get("translation"), f"{label}.translation", errors)
                axis = value.get("axis")
                if _vec3(axis, f"{label}.axis", errors):
                    length = math.sqrt(sum(float(item) ** 2 for item in axis))
                    if not math.isclose(length, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                        errors.append(f"{label}.axis must be a nonzero unit vector")
                if value.get("purpose") != "rotation":
                    errors.append(f"{label}.purpose must be rotation")
            elif collection_name == "sockets":
                _vec3(value.get("translation"), f"{label}.translation", errors)
                _vec3(value.get("rotationDegrees"), f"{label}.rotationDegrees", errors)
                if not isinstance(value.get("tags"), list) or not all(isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in value["tags"]):
                    errors.append(f"{label}.tags must contain IDs")
                elif len(value["tags"]) != len(set(value["tags"])):
                    errors.append(f"{label}.tags must be unique")
            elif collection_name == "collisions":
                if value.get("type") != "box" or value.get("isTrigger") is not False:
                    errors.append(f"{label} must be a non-trigger box")
                _vec3(value.get("translation"), f"{label}.translation", errors)
                _vec3(value.get("dimensions"), f"{label}.dimensions", errors, positive=True)
                roles = value.get("layerRoles")
                if not isinstance(roles, list) or not roles or not all(
                    isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in roles
                ):
                    errors.append(f"{label}.layerRoles must contain IDs")
                elif len(roles) != len(set(roles)):
                    errors.append(f"{label}.layerRoles must be unique")
            elif collection_name == "lods":
                if value.get("level") != 1:
                    errors.append(f"{label}.level must be 1")
                _finite_number(value.get("distanceMeters"), f"{label}.distanceMeters", errors, minimum=0, exclusive_minimum=True)
                ratio = value.get("targetRatio")
                if _finite_number(ratio, f"{label}.targetRatio", errors, minimum=0, maximum=1, exclusive_minimum=True):
                    if float(ratio) >= 1:
                        errors.append(f"{label}.targetRatio must be < 1")
                source_ids = value.get("sourceNodeIds")
                if not isinstance(source_ids, list) or not source_ids or any(item not in node_ids for item in source_ids):
                    errors.append(f"{label}.sourceNodeIds must reference existing nodes")
                elif len(source_ids) != len(set(source_ids)):
                    errors.append(f"{label}.sourceNodeIds must be unique")
