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
- Blender has a bounded default timeout. The native runners share `backends/process.py`: on POSIX each tool
  has an owned process group, timeout/cancellation escalates from TERM to KILL and drains output with a deadline.
  Main-thread CLI cancellation propagates even when an outer Factory job terminates its wrapper. Failed Blender
  runs remove partial GLBs. This cleans up trusted tools, not deliberately detached/daemonizing processes.
- A nonempty output directory is allowed only when it contains no backend-owned output names.
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

```bash
python3 -m backends.blender.examples.armored_vehicle_spec --out local-data/vehicle.input.spec.json
python3 -m backends.blender.runtime.run_backend \
  --spec local-data/vehicle.input.spec.json \
  --output local-data/armored-vehicle
```

Set `BLENDER_EXECUTABLE`, pass `--blender`, or put Blender on `PATH`. Missing tools fail with a configuration error;
there is no Windows-path fallback. The proof
produces a three-part hull/turret/weapon hierarchy, one collider, one rotation pivot, two sockets,
one painted-metal material, and a 50% triangle-count far LOD. Geometry dimensions are baked while
node scale remains identity. The manifest's bounds, node indices, triangle counts, and hashes are
read from the exported GLB rather than predicted.

Validate the graph and manifest with:

```bash
python3 scripts/validate-json-schema.py \
  backends/blender/schema/constructive_graph.schema.json \
  local-data/armored-vehicle/constructive_graph.json
python3 scripts/validate-json-schema.py \
  schemas/asset_manifest.schema.json \
  local-data/armored-vehicle/asset_manifest.json
```

Run the focused suite with:

```bash
TMPDIR=/var/tmp python3 -m unittest backends.blender.tests.test_graph backends.blender.tests.test_process
# Only when changing actual Blender generation:
TMPDIR=/var/tmp python3 -m unittest backends.blender.tests.test_blender_integration
```

This is a hard-surface blockout proof, not a general asset generator or production-readiness
claim. Adoption still needs relevant visual, rights and runtime checks in the consuming game;
it does not require a new Factory campaign or an unrelated broad batch.
