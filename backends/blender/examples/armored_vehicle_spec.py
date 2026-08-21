#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path

from forge.stage2_spec.new_sculpt_spec import make_spec


PAINT_RGBA = "rgba(62, 76, 54, 1.0)"
PAINT_DARK_RGBA = "rgba(38, 47, 34, 1.0)"


def _component(
    template: dict,
    *,
    component_id: str,
    name: str,
    level: str,
    role: str,
    primitive: str,
    parent: str | None,
    position: list[float],
    dimensions: tuple[float, float, float],
    bevel_radius: float,
) -> dict:
    result = copy.deepcopy(template)
    result.update(
        {
            "id": component_id,
            "name": name,
            "level": level,
            "role": role,
            "importance": 1.0 if level == "macro" else 0.9,
            "confidence": 1.0,
            "primitive": primitive,
            "topologyClass": "assembled-solid",
            "topologyRationale": "Deterministic hard-surface blockout built from an allowlisted primitive.",
            "parent": parent,
            "attachment": None,
            "dimensions": {
                "width": dimensions[0],
                "height": dimensions[1],
                "depth": dimensions[2],
                "units": "meters",
                "confidence": 1.0,
            },
            "transform": {
                "position": position,
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            "material": "painted-metal",
            "materialLayers": ["painted-metal"],
            "colorMaterialRecipe": {
                "dominantAlbedo": PAINT_RGBA,
                "secondaryAlbedo": PAINT_DARK_RGBA,
                "materialClass": "metal",
                "materialClassConfidence": 1.0,
            },
            "evidenceRefs": ["full-object"],
            "fidelityTier": "blockout",
        }
    )
    result["geometryDescriptor"] = {
        "topologyIntent": "closed hard-surface primitive with stable semantic origin",
        "edgeTreatment": {"type": "bevel", "bevelRadius": bevel_radius, "segments": 2},
        "deformationStack": [],
        "uvStrategy": "generated procedural coordinates",
        "normalStrategy": "weighted vertex normals from generated geometry",
    }
    result["actionProfile"]["animationRole"] = "root" if parent is None else "attached"
    result["actionProfile"]["sockets"] = []
    result["actionProfile"]["collider"] = None
    result["actionProfile"]["destruction"]["debrisMaterial"] = "painted-metal"
    return result


def make_armored_vehicle_spec() -> dict:
    spec = make_spec("Generic RTS Armored Vehicle", None)
    spec["suitability"] = "pass"
    for score_name in spec["scores"]:
        spec["scores"][score_name] = 3

    assessment = spec["preSpecAssessment"]
    assessment["objectClass"] = {
        "primaryType": "armored vehicle",
        "primaryDomain": "object",
        "formLanguage": ["hard-surface", "low-profile"],
        "structureKind": ["assembled"],
        "motionPotential": ["turret-yaw"],
        "materialFamilies": ["painted-metal"],
        "notes": "Generic benchmark blockout; no game-specific design references are used.",
    }
    complexity = assessment["complexity"]
    complexity["tier"] = "moderate"
    for score_name in complexity["scores"]:
        complexity["scores"][score_name] = 3
    complexity["estimatedCounts"] = {
        "macroComponents": 1,
        "mesoComponents": 2,
        "microFeatureGroups": 0,
        "materialLayers": 1,
        "repetitionSystems": 0,
    }
    complexity["reasoning"] = ["One hull, one independently rotating turret, and one socketed weapon define the proof hierarchy."]
    assessment["specDepthDecision"] = {
        "requiredDepth": "moderate",
        "minimumComponentLevels": ["macro", "meso"],
        "needsRepetitionSystems": False,
        "needsMaterialLocalOverrides": False,
        "needsMultipleReviewViews": True,
        "needsActionReadyHierarchy": True,
        "rationale": "The proof requires a movable turret and attached weapon but no micro-detail system.",
    }
    assessment["unknownsToResolveBeforeImplementation"] = []

    quality = spec["qualityContract"]
    quality["qualityBar"] = "vertical-slice-blockout"
    quality["minimumSpecDepth"] = {
        "macroComponents": 1,
        "mesoComponents": 2,
        "microFeatureGroups": 0,
        "materialLayers": 1,
        "repetitionSystems": 0,
        "reviewViewpoints": 3,
    }

    template = spec["componentTree"][0]
    hull = _component(
        template,
        component_id="hull",
        name="Hull",
        level="macro",
        role="body",
        primitive="box",
        parent=None,
        position=[0.0, 0.6, 0.0],
        dimensions=(3.2, 1.0, 5.0),
        bevel_radius=0.12,
    )
    hull["geometryDescriptor"]["deformationStack"] = [{"operation": "mirror", "axis": "X"}]
    hull["actionProfile"]["collider"] = {
        "type": "box",
        "offset": [0.0, 0.0, 0.0],
        "scale": [3.0, 0.9, 4.6],
        "isTrigger": False,
        "notes": "Single bounded gameplay proxy for the vertical slice.",
    }

    turret = _component(
        template,
        component_id="turret",
        name="Turret",
        level="meso",
        role="rotating-assembly",
        primitive="box",
        parent="hull",
        position=[0.0, 0.85, 0.2],
        dimensions=(1.8, 0.65, 2.1),
        bevel_radius=0.10,
    )
    turret["geometryDescriptor"]["deformationStack"] = [{"operation": "mirror", "axis": "X"}]
    turret["actionProfile"]["animationRole"] = "turret-yaw"
    turret["actionProfile"]["pivot"] = {
        "mode": "rotation",
        "localPosition": [0.0, 0.0, 0.0],
        "axis": [0.0, 1.0, 0.0],
        "confidence": 1.0,
    }
    turret["actionProfile"]["sockets"] = [
        {"id": "primary-weapon", "localPosition": [0.0, 0.0, 1.0], "localRotation": [1.57079632679, 0.0, 0.0]}
    ]

    weapon = _component(
        template,
        component_id="weapon",
        name="Primary weapon",
        level="meso",
        role="barrel",
        primitive="cylinder",
        parent="turret",
        position=[0.0, 0.0, 0.0],
        dimensions=(0.28, 0.28, 2.8),
        bevel_radius=0.025,
    )
    weapon["attachment"] = {
        "parentSocket": "primary-weapon",
        "localStart": [0.0, 0.0, 1.0],
        "localEnd": [0.0, 0.0, 3.8],
        "contactType": "socket-joint",
        "baseRadius": 0.14,
        "endRadius": 0.14,
        "embedDepth": 0.05,
        "gapTolerance": 0.005,
        "evidenceRefs": ["full-object"],
    }
    weapon["actionProfile"]["animationRole"] = "weapon-elevation"
    weapon["actionProfile"]["sockets"] = [
        {"id": "muzzle-vfx", "localPosition": [0.0, 0.0, 2.8], "localRotation": [1.57079632679, 0.0, 0.0]}
    ]

    spec["componentTree"] = [hull, turret, weapon]
    material = spec["materials"][0]
    material["id"] = "painted-metal"
    material["name"] = "Painted metal"
    material["baseColor"] = "#3E4C36"
    material["color"] = "#3E4C36"
    material["metalness"]["base"] = 0.85
    material["roughness"]["base"] = 0.48
    material["dirt"]["amount"] = 0.1

    component_ids = ["hull", "turret", "weapon"]
    for build_pass in spec["buildPasses"]:
        build_pass["componentRefs"] = component_ids
    spec["featureReviewTargets"] = [
        {
            "id": "vehicle-silhouette",
            "name": "Hull and turret silhouette",
            "tier": "critical",
            "passIds": ["blockout"],
            "minimumScore": 0.8,
            "mustPass": True,
            "componentRefs": ["hull", "turret"],
            "evidenceRefs": ["full-object"],
        },
        {
            "id": "turret-weapon-hierarchy",
            "name": "Turret pivot and socketed weapon hierarchy",
            "tier": "critical",
            "passIds": ["structural-pass", "interaction-pass"],
            "minimumScore": 0.8,
            "mustPass": True,
            "componentRefs": ["turret", "weapon"],
            "evidenceRefs": ["full-object"],
        },
        {
            "id": "painted-metal-response",
            "name": "Painted metal response",
            "tier": "critical",
            "passIds": ["material-pass", "surface-pass"],
            "minimumScore": 0.75,
            "mustPass": True,
            "componentRefs": component_ids,
            "evidenceRefs": ["full-object"],
        },
    ]
    spec["actionReadiness"]["rootMotionNode"] = "hull"
    spec["lodPlan"] = [
        {"tier": "near", "distance": 0, "strategy": "full component tree and material layers", "materialIds": ["painted-metal"]},
        {
            "tier": "far",
            "distance": 30,
            "strategy": "reduce all render meshes",
            "targetRatio": 0.5,
            "componentRefs": component_ids,
            "materialIds": ["painted-metal"],
        },
    ]
    spec["lightingFromPhoto"] = [
        "neutral key light with ACES exposure",
        "low-intensity fill light",
        "rim environment light with contact shadow",
    ]
    spec["coordinateFrame"] = {
        "unit": "meter",
        "handedness": "right",
        "upAxis": "+Y",
        "forwardAxis": "+Z",
    }
    spec["silhouette"].update(
        {
            "boundingShape": "low armored hull with a centered turret and long forward barrel",
            "aspectRatios": ["width:height 3.2:1.85", "length:width 5:3.2"],
            "symmetry": "bilateral across X except for future surface detail",
            "dominantCurves": ["beveled rectangular hull", "compact beveled turret"],
            "negativeSpaces": ["clear separation below weapon barrel"],
            "landmarks": ["turret pivot", "primary weapon socket", "muzzle socket"],
        }
    )
    return spec


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    write_json_atomic(args.out.resolve(), make_armored_vehicle_spec())
    print(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
