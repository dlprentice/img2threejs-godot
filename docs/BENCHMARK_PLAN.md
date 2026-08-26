# Benchmark plan

## Purpose

These benchmarks decide whether the Blender/Godot route is reliable enough to become a dependency.
They do not compare which renderer makes the prettiest hero image. They measure unattended asset
generation, portable structure, Godot import behavior, gameplay-camera readability, runtime cost,
and repair burden.

All public benchmark inputs must be generic and redistributable. Project art bibles, proprietary
references, private prompts, and game assets remain in a separate private workspace.

## Benchmark set

1. **RTS armored combat vehicle** — asymmetrical turret or weapon mount, hull, wheels/tracks,
   readable faction surfaces, muzzle/VFX socket, selection pivot, useful collision, and at least one
   reduced LOD.
2. **RTS industrial production or defense building** — large readable silhouette, repeated
   structural modules, entrance or firing orientation, construction/VFX anchors, footprint
   collision, navigation obstacle metadata, and LODs.
3. **Isometric zombie-game prop** — choose one generic barricade, vehicle prop, or damaged
   storefront. It must preserve damage language and negative space at isometric distance, provide
   collision and destruction groups, and avoid excessive material/draw-call fragmentation.
4. **Unattended batch of ten hard-surface assets** — run only after the first three subjects expose
   and close the basic backend/import failures. The batch must use fixed prompts/specs, pinned tool
   versions, and no per-asset code changes during the run.

## Controlled procedure

For every asset:

1. Freeze the source brief/spec, reference set, target budgets, generator revision, upstream
   baseline, Blender version, Godot version, and camera profile.
2. Run from a clean asset output directory with no interactive Blender changes.
3. Preserve stage logs, hashes, the GLB, manifest, Godot import report, generated scene, renders,
   and performance capture.
4. Run deterministic technical gates before multimodal review.
5. If a gate fails, record exactly one repair action and rerun from the earliest invalid stage.
6. Stop at the configured retry ceiling; mark the asset rejected rather than editing its mesh by
   hand.
7. Capture the accepted artifact again from a clean Godot import to rule out editor cache state.

The Three.js path remains a regression comparison for shared inputs. It is not required to produce
identical pixels, but its existing tests must remain green and overlapping semantic IDs should be
traceable between outputs.

## Required evidence per asset

- Immutable source specification and hashes of all admitted references.
- Constructive graph and per-stage status records.
- Blender/tool versions, seed, command, duration, and output hashes.
- GLB plus a schema-valid `asset_manifest.json`.
- Independent GLB validation report.
- Godot import log, warning/error classification, generated scene, and resource inventory.
- Neutral turntable, RTS camera, and/or isometric camera images as applicable.
- Collision, socket, pivot, LOD, and navigation inspection evidence.
- Triangle, mesh, material, texture, draw-call, memory, and frame-time measurements.
- Visual-review record and complete retry history.
- Human-intervention record, including whether any mesh vertices, UVs, weights, or topology were
  edited manually.

## Acceptance measurements

Each benchmark brief must supply asset-specific budgets before generation. A result cannot move its
budget after seeing the output.

| Measurement | Method | Acceptance rule |
| --- | --- | --- |
| Silhouette readability | Masked Godot render at target gameplay resolution; human/multimodal review | Primary mass, facing, and role are readable at the intended camera distance; every critical silhouette feature passes its declared threshold. |
| Reference similarity | Fixed-camera comparison with per-feature scores | No mandatory reference feature is missing; overall score meets the brief threshold and cannot override technical failures. |
| Project art-style consistency | Blind review against the approved generic style board in the benchmark workspace | Pass/fail plus rationale; public fork records only the result and generic style dimensions, not private references. |
| Triangle count | GLB and imported Godot mesh statistics | At or below the predeclared total and per-LOD budgets. |
| Mesh and material count | Manifest versus Godot imported-resource inventory | Counts agree; at or below budget; unexpected splits or fused semantic parts fail. |
| Texture count and resolution | Manifest/file scan/Godot resource inspection | Counts and dimensions agree with files, are within budget, and no texture exceeds the declared maximum. |
| Missing texture detection | Resolve every material texture binding after a clean import | Zero unresolved, placeholder, or silently substituted required textures. |
| Scale and orientation | Compare manifest bounds/axes with Godot world measurements | Metric scale is within 1% of the declared dimensions; up/forward axes match the profile; asset rests on its declared ground plane. |
| Origin and pivot correctness | Transform probes in Godot | Root origin and every declared pivot match the intended rotation/placement point within the brief tolerance. |
| Socket correctness | Attach visible probe scenes and evaluate local/world transforms | Every required socket resolves to the correct parent, orientation, and position; no missing or root-fallback socket. |
| Collision usefulness | Debug-shape render plus scripted overlap/raycast samples | Required collision exists, follows the usable gameplay volume, has no blocking void-fill mistakes, and respects the collider budget. |
| LOD availability | Imported mesh/resource inspection and camera-distance capture | Every required level exists, transitions in declared order, reduces triangles monotonically, preserves material/socket identity, and shows no critical silhouette pop. |
| GLB validation | Independent validator plus manifest cross-check | Zero structural errors; buffers, accessors, images, node references, transforms, and declared extensions resolve. |
| Godot import warnings/errors | Clean headless/editor import with captured logs | Zero import errors. Warnings require explicit allow-list entries and may not indicate missing resources, invalid transforms, unsupported materials, or corrupt geometry. |
| Rendering correctness | Godot neutral and gameplay-camera captures | No missing surfaces, inverted normals, broken alpha, z-fighting, shader fallback, clipped bounds, or unintended culling. |
| Gameplay-camera readability | RTS/isometric capture at target resolution and zoom | Asset role, facing, team-color zones, damage state, and interactive anchors remain legible as applicable. |
| Draw-call impact | Godot frame/resource profiler in the standardized preview scene | At or below the predeclared isolated-asset budget; repeated elements use instancing or justified alternatives. |
| Frame-time impact | Median and 95th-percentile frame time after warm-up | Within the predeclared budget on the benchmark machine; record CPU and GPU time separately when available. |
| Repair attempts | Manifest retry history and stage logs | No accepted asset exceeds three automated repair attempts; the batch report includes median and maximum. |
| Token or API cost | Provider usage record linked to the attempt ID | At or below the predeclared per-asset cap; failed attempts count toward cost. Local deterministic work is recorded separately. |
| Human mesh-editing requirement | Intervention log and artifact provenance | Promotion assets require no manual vertex, edge, face, topology, UV, skin-weight, or collision-mesh editing. Brief/spec changes and accept/reject review are recorded but are not mesh editing. |

## Mandatory Godot technical gates

An asset cannot be accepted unless all of these pass:

- manifest syntax/schema and referenced-file hashes;
- GLB structural validation;
- clean Godot import with zero errors and no disallowed warnings;
- metric scale, ground placement, and forward/up orientation;
- declared root origin, pivots, and required sockets;
- required collision shapes and navigation metadata;
- required LOD presence, ordering, and triangle reduction;
- required materials and textures with no missing resources;
- render correctness in neutral and applicable gameplay cameras;
- triangle, material, texture, and draw-call budgets.

Visual approval never waives one of these gates.

## Standardized camera profiles

### RTS profile

- Perspective or shallow-perspective camera fixed by the benchmark profile.
- Three-quarter elevated view plus front/side diagnostic views.
- Captures at target gameplay resolution and one enlarged inspection resolution.
- Neutral light for technical review; a separate gameplay light may be captured but cannot replace
  the neutral result.

### Isometric profile

- Fixed orthographic size, azimuth, elevation, background, exposure, and shadow settings.
- Four quarter-turn captures to expose hidden flatness, holes, and incorrect damage placement.
- One target-resolution capture used for readability scoring.

Camera transforms and render settings are versioned inputs and written into the validation results.

## Repair accounting

A repair attempt begins when an accepted source spec produces a failed stage or gate and a change is
made to regenerate it. Each retry record includes stage, observed failure, action, input/output
hashes, cost, duration, and outcome. Changing several unrelated parameters in one attempt is not
allowed because it prevents attribution.

Manual mesh editing means direct manipulation of geometry, topology, UVs, skin weights, or collision
meshes in Blender or Godot. Editing a declarative spec or constructor parameter is allowed but counts
as a repair attempt. Backend source changes invalidate an unattended batch and require a fresh batch.

## Promotion decision

Recommend promotion to a private game integration only when:

- at least **8 of the 10** unattended batch assets pass without human mesh editing;
- every accepted asset passes every mandatory Godot technical gate;
- the existing Three.js regression tests still pass;
- no accepted result exceeds the repair or cost ceiling; and
- failures are reported as rejects rather than silently repaired with stale output or manual edits.

Anything less remains an experiment. The report should name the failing constructor, boundary, or
gate and recommend the smallest next backend improvement.
