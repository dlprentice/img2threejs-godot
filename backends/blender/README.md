# Blender backend

Status: experimental vertical slice implemented and benchmarked. It converts a validated
`ObjectSculptSpec` into a closed constructive graph, runs a fixed Blender script headlessly, and
emits a GLB plus an engine-neutral `asset_manifest.json`. It never evaluates Python or arbitrary
`bpy` fragments from input data.

## Initial constructor allow-list

- rounded box
- cylinder
- bevel
- mirror
- material assignment
- socket
- pivot
- collision proxy

The implemented slice also creates a measured reduced LOD with Blender's decimator. Lathe,
extrusion, curve sweep, array, boolean cut, panel inset, decal planes, and general UV processing
remain unsupported and fail closed.

## Execution contract

- Input is validated before Blender starts; unknown operations or fields fail closed.
- Inputs use explicit metric units, handedness, axes, stable IDs, local transforms, and deterministic
  seeds.
- The runner starts from a clean scene, uses no user addons or preferences, performs no network
  access, and writes only inside the selected asset output directory.
- Object names, hierarchy, modifier order, and export order are stable for identical inputs.
- Materials use independent PBR channels with explicit color spaces and provenance.
- Render geometry, collision proxies, pivots, and sockets remain separate named objects.
- Export is atomic: a failed run must not leave a manifest that marks a partial GLB successful.
- The result records Blender/Python versions, input and output hashes, timings, warnings, and errors.

## Output contract

```text
<asset-id>/
  asset.glb
  asset_manifest.json
  textures/                 # only when external texture files are required
  evidence/                 # deterministic previews and validation reports
```

Paths in the manifest are relative to its directory. The manifest must validate against
`schemas/asset_manifest.schema.json` and contain no executable payload.

## Armored-vehicle proof

From the repository root:

```powershell
python -m backends.blender.examples.armored_vehicle_spec --out runtime/vehicle.input.spec.json
python -m backends.blender.runtime.run_backend `
  --spec runtime/vehicle.input.spec.json `
  --output runtime/armored-vehicle
```

Set `BLENDER_EXECUTABLE` when Blender is not installed at the default Windows location. The proof
produces a three-part hull/turret/weapon hierarchy, one collider, one rotation pivot, two sockets,
one painted-metal material, and a 50% triangle-count far LOD. Geometry dimensions are baked while
node scale remains identity. The manifest's bounds, node indices, triangle counts, and hashes are
read from the exported GLB rather than predicted.

Validate the graph and manifest with:

```powershell
uv run --with jsonschema==4.25.1 python scripts/validate-json-schema.py `
  backends/blender/schema/constructive_graph.schema.json `
  runtime/armored-vehicle/constructive_graph.json
uv run --with jsonschema==4.25.1 python scripts/validate-json-schema.py `
  schemas/asset_manifest.schema.json `
  runtime/armored-vehicle/asset_manifest.json
```

Run the focused suite with:

```powershell
python -m unittest backends.blender.tests.test_graph
python -m unittest backends.blender.tests.test_blender_integration
```

This is a hard-surface blockout proof, not a general asset generator or production-readiness
claim. Promotion still requires broader unattended batches, visual review, licensing, and
game-specific validation outside this public repository.
