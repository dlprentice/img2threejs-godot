# Blender and Godot adaptation plan

## Status and boundary

This is a bootstrap design for an experimental, generic asset-generation backend. It is not a game
migration, and no game may depend on it until the benchmark policy in `BENCHMARK_PLAN.md` passes.
Game-specific prompts, art direction, assets, import presets, and gameplay wrappers belong in a
separate private workspace repository.

The adaptation keeps the current Three.js route working as the regression backend. Blender and
Godot are additive consumers of validated, declarative data; they are not replacements for the
upstream generator during the proof of concept.

## Verified upstream architecture

The following map is based on source and tests at the baseline commit, not only README claims.

| Concern | Implemented authority | Finding |
| --- | --- | --- |
| Asset specification | `forge/stage2_spec/new_sculpt_spec.py` and `validate_sculpt_spec.py` | `ObjectSculptSpec` schema version 2.1 is authored and validated in Python. It is not currently expressed as a standalone JSON Schema. |
| Component model | `componentTree`, `materials`, `repetitionSystems`, `actionProfile`, `attachment` | Named parent-child parts carry transforms, topology intent, material bindings, pivots, sockets, collider intent, destruction data, and evidence references. |
| Resumability | `forge/_shared/workflow_state.py`, `forge/state.py`, `forge/next.py` | An atomically written checklist records evidence and bounded retry counts. It is an index; the spec, review history, and gates remain authoritative. |
| Pass state | `forge/stage3_build/orchestrate_passes.py` | Ordered pass credit is derived from `reviewHistory`; visual passes require screenshot, comparison, global score, and feature gates. |
| Three.js generation | `forge/stage3_build/generate_threejs_factory.py` | A fixed primitive set emits a TypeScript `THREE.Group`, materials, named nodes, sockets, collider metadata, destruction groups, lights, camera helpers, and browser-specific helpers. |
| Deterministic review | `forge/stage4_review/` | Strict spec checks, Tier 1 diagnostics, Divine Eye, multi-angle and turntable checks, self/pairwise intersection, part coverage, attachment, material, and bounded correction gates exist as separate tools. |
| Rendering evidence | `render_bridge.py`, `scripts/capture_threejs_playwright.py` | Python records and validates evidence; the real browser route must produce pixels. Playwright is optional and outside the stdlib-only core. |
| Materials | `forge/materials/reference.py`, `docs/materials/material-reference.json` | A versioned, explicitly Three.js material registry supplies priors. Image evidence and confidence decide whether an assignment can proceed. |
| GLB support | `probe_glb.py`, `mesh_reference_compare.py`, `integrations/mesh3d/` | GLB can be inspected or used as reference evidence. There is no implemented candidate GLB exporter. |
| Blender/Godot support | none | No `bpy` backend, Blender scene builder, Godot importer, wrapper generator, or gameplay-camera validator exists. |

### What to reuse unchanged

- Reference admission, image probing, evidence hashes, provenance, and uncertainty handling.
- The local workflow state, ordered pass model, bounded repair loop, and exact next-action reporting.
- The distinction between deterministic gates and multimodal judgment.
- Detail inventory, feature targets, per-region confidence, and the rule that hidden geometry is not
  invented with false confidence.
- Semantic component IDs, parentage, attachment contracts, pivots, sockets, collider intent, and
  destruction groups.
- Part coverage, attachment, performance-budget, and evidence-record concepts.
- The existing TypeScript/Three.js generator and its tests as a regression backend.

### What needs a backend-neutral interface

- Geometry constructors and topology descriptions.
- PBR material channels and texture binding semantics.
- Coordinate system, metric scale, transforms, pivots, and sockets.
- Collision and LOD descriptions.
- UV generation, texture baking, artifact export, and file hashing.
- Preview-camera profiles and render evidence.
- Technical validation results and packaging results.

### What should remain Three.js-specific

- `THREE.Group`, `THREE.Mesh`, `THREE.SkinnedMesh`, and `root.userData.sculptRuntime` emission.
- `MeshStandardMaterial`/`MeshPhysicalMaterial` construction and the current Three.js material
  registry values.
- `WebGLRenderer`, PMREM/`RoomEnvironment`, OrbitControls, EffectComposer, browser readiness hooks,
  and browser capture adapters.
- The existing TypeScript factory helper implementations and showcase typecheck contract.

## Target data flow

```text
reference or generic asset brief
  -> validated ObjectSculptSpec and evidence
  -> specification intake adapter
  -> constrained constructive scene graph
  -> blockout -> structure -> form -> materials -> surface -> optimization
  -> deterministic Blender backend
  -> GLB + asset_manifest.json
  -> Godot import + inherited/wrapper scene
  -> standardized RTS/isometric gameplay-camera renders
  -> deterministic technical gates + multimodal visual review
  -> accept | repair | regenerate | reject
```

`ObjectSculptSpec` remains the Three.js source contract during the experiment. The intake adapter
must project its reusable semantics into a constrained constructive scene graph without changing
the original spec or teaching the Blender backend to interpret Three.js code. The constructive graph
should be versioned only when the first proof-of-concept constructor set is implemented; creating a
large speculative schema before then would freeze untested fields.

## Backend boundaries

Every boundary is deterministic, file-based, and fail-closed. A failure returns a structured result
with stage, asset ID, input hashes, error code, human-readable message, and retryability. No boundary
may execute a string from a spec or manifest.

| Boundary | Input | Output and responsibility |
| --- | --- | --- |
| Specification intake | Strict-valid `ObjectSculptSpec`, source/evidence hashes, baseline SHA | Canonical IDs, explicit metric units and axes, normalized transforms, allowed constructor calls, and a stable intake hash. Reject unsupported or ambiguous semantics. |
| Geometry construction | Constrained constructor nodes and parameters | Named Blender objects/collections with stable hierarchy and geometry hashes. No agent-authored `bpy` source. |
| Material construction | Neutral PBR channel records with provenance and color spaces | Blender material nodes, independent maps, and a portable glTF-compatible binding report. Preserve unsupported channels as explicit validation warnings. |
| Socket and pivot creation | Component IDs, local transforms, purposes, axes | Named empties/bones with stable parent-local transforms and manifest entries. |
| Collider generation | Declarative primitive/convex/concave collision intent | Separate named collision proxies; never silently reuse render meshes as expensive collision meshes. |
| LOD generation | Source mesh IDs, budgets, screen/distance thresholds | Deterministic LOD meshes and counts, with provenance back to the source mesh and reduction settings. |
| UV and texture processing | Meshes, UV policy, channel sources, resolution budget | UV sets, baked/copied textures, hashes, color-space declarations, and missing-channel results. |
| Asset export | Scene graph, selected LODs, materials, anchors, license data | One GLB plus `asset_manifest.json`; export must be repeatable from the same inputs and tool versions. |
| Preview rendering | Exported GLB or imported Godot scene plus a named camera profile | Stable PNG captures and performance samples. Blender preview is diagnostic; Godot gameplay-camera output is authoritative. |
| Technical validation | GLB, manifest, file set, budgets | Schema, file, glTF, hierarchy, counts, transform, collision, LOD, texture, and Godot import results. |
| Visual review | Standardized renders, reference/brief, deterministic results | Per-view and per-feature decision with one action: accept, repair, regenerate, or reject. A visual score cannot override a failed mandatory technical gate. |
| Godot packaging | Validated GLB and manifest | Imported resource mapping, inherited or wrapper scene, collisions, LODs, sockets, overrides, VFX anchors, navigation metadata, preview scenes, and captured import diagnostics. |

## Blender backend policy

The backend owns Blender API details. Agents select constructors and bounded parameters; they do not
write arbitrary scripts. The initial allow-list is:

- rounded box
- cylinder
- lathe
- extrusion
- curve sweep
- array
- mirror
- bevel
- boolean cut
- panel inset
- decal plane
- socket
- pivot
- collision proxy
- material assignment

The graph may compose constructors but may not embed Python, expressions, driver source, shell
commands, addon calls, or network locations. `additionalProperties: false`-style validation and an
explicit operation discriminator should make unsupported input fail before Blender launches.

Determinism requirements:

- Pin and record Blender, Python, exporter, and schema versions.
- Start from a clean scene and do not depend on user preferences or installed addons.
- Use explicit units, axes, transforms, seeds, modifier order, object ordering, and export options.
- Sort input nodes by stable ID and generate stable Blender object names.
- Run headless for benchmark generation; keep interactive files diagnostic only.
- Write to a fresh asset-specific output directory and hash every emitted artifact.
- Disable network access in the backend process and accept only workspace-relative inputs.
- Emit machine-readable failures; never leave a partially exported GLB marked successful.

The first implementation should support only rounded box, cylinder, bevel, mirror, material
assignment, socket, pivot, and collision proxy—enough for an armored-vehicle blockout. Add another
constructor only when a benchmark demonstrates that the existing set cannot express a required
shape.

## Godot integration policy

Godot is the final rendering and import authority because it observes the actual engine importer,
resource conversion, scene hierarchy, shader compatibility, culling, and gameplay camera.

The integration must provide:

- GLB import with captured warnings and errors.
- A generated inherited scene when inheritance is sufficient, otherwise a small wrapper scene.
- Collision assignment from manifest collision records.
- LOD configuration from manifest levels and thresholds.
- Socket mapping to stable `Node3D`/`Marker3D` nodes.
- Faction material overrides without duplicating geometry.
- VFX-scene attachment by declared anchor role.
- Navigation metadata and obstacle configuration.
- Import-error capture as a required validation artifact.
- Standardized neutral preview, RTS camera, and isometric camera scenes.
- Rendering-correctness captures and bounded draw-call/frame-time measurements.

Generated Godot files must reference generic IDs and relative asset paths. They must not contain
game scripts, proprietary resource paths, or assumptions about either game repository. A private
workspace may map generic roles such as `primary_weapon`, `muzzle_vfx`, or `faction_surface` to a
specific project later.

## Engine-neutral manifest

`schemas/asset_manifest.schema.json` is the initial output contract. It records:

- asset identity/version and source-specification provenance;
- generator version and exact upstream baseline;
- units, scale, handedness, forward axis, and up axis;
- artifacts, mesh nodes, materials, textures, LODs, collisions, pivots, and sockets;
- animation hooks, VFX anchors, destruction groups, and navigation metadata;
- triangle/mesh/material/texture counts and texture resolutions;
- license/provenance, deterministic validation, visual review, and retry history;
- optional Godot packaging evidence.

The schema is deliberately declarative and closed. It has no JavaScript, Python, command, callback,
or expression field. Consumers must treat every string as data and must never evaluate manifest
content.

## Proposed repository layout

```text
backends/
  blender/
    README.md
integrations/
  godot/
    README.md
schemas/
  asset_manifest.schema.json
docs/
  UPSTREAM_BASELINE.md
  BLENDER_GODOT_ADAPTATION_PLAN.md
  BENCHMARK_PLAN.md
```

Directories contain focused contract files; no empty placeholder directories are introduced. The
private workspace repository is intentionally absent from this public fork.

## Validation order

1. Validate the source spec with upstream strict-quality rules.
2. Validate and hash the constructive scene graph before Blender starts.
3. Build in ordered stages and record a stage result for every asset.
4. Validate Blender object hierarchy, transforms, names, material slots, and budgets.
5. Export GLB and write the manifest atomically.
6. Validate manifest syntax/schema, referenced files/hashes, and GLB structure.
7. Import into a clean Godot validation project and capture importer diagnostics.
8. Validate scene hierarchy, sockets, pivots, collisions, LODs, scale, and axes.
9. Capture standardized Godot gameplay-camera renders and performance measurements.
10. Run multimodal review only after mandatory technical gates pass.

The current Three.js test suite remains required throughout. A Blender/Godot result does not excuse
a regression in the existing backend.

## Proof-of-concept sequence

1. Implement the smallest constructive graph and Blender runner for one armored vehicle blockout.
2. Export a GLB and complete manifest with one LOD, one collider, one pivot, and two sockets.
3. Import into an isolated Godot validation project and produce RTS-camera evidence.
4. Compare the same validated spec through the unchanged Three.js regression route where its
   constructors overlap.
5. Run the first three benchmark subjects and fix only reproduced boundary failures.
6. Run the unattended ten-asset batch. Do not propose game adoption unless the promotion gate passes.

The single next implementation task is step 1: define and implement the minimal constrained scene
graph plus the rounded-box/cylinder Blender constructors for the armored-vehicle blockout.

## Upstream defects and synchronization risks

- Release metadata is stale relative to the `v1.5-beta` release (`1.4.4` in README/SKILL and
  `1.4.4-beta.2` at the changelog head).
- `grimoire/scripts.md` calls the starter schema 2.0, while the author emits 2.1. Its documented pass
  list also omits `surface-pass`, which exists in source.
- `runtime/scripts/export_mesh_geometry.mjs` is documented and invoked by
  `scripts/character_audit.sh`, but `runtime/` is absent.
- `docs/PLAN_1.5_ANIMATION_READY_RIGS.md` is cited by the research note but is absent.
- The research note proposes `forge/stage2_structure/` and `_shared/part_shell.py`; neither exists.
  `open-shell` validation exists, but there is no dedicated part-shell implementation.
- GLB is a reference/evidence format only; there is no candidate GLB export path.
- Runtime Three.js compile tests skip without a separate showcase checkout unless
  `IMG2THREEJS_REQUIRE_SHOWCASE=1` is set.
- On the captured Windows runtime, the documented unittest command hits three existing Unicode
  failures under the default `cp1252` locale; the full suite passes with `PYTHONUTF8=1`.
- Pass-completion logic is duplicated across validator, orchestrator, generator, and local workflow
  state, increasing drift risk.
- The skill text states both knife-plus-Glock support and, later, knife-only support.
- Optional vision and hosted mesh integrations use third-party dependencies despite the core's
  stdlib-only contract; they must stay isolated and non-authoritative.

All adaptation code should live behind new directories and narrow adapters. Changes to upstream core
files require a reproduced integration need, a focused test, and a clear synchronization rationale.
