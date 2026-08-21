# Blender backend contract

Status: design scaffold only. No Blender backend is implemented by this bootstrap.

This backend will interpret a validated, constrained constructive scene graph and emit a GLB plus
an engine-neutral `asset_manifest.json`. It must not accept agent-authored Python or arbitrary
`bpy` fragments.

## Initial constructor allow-list

- rounded box
- cylinder
- bevel
- mirror
- material assignment
- socket
- pivot
- collision proxy

Lathe, extrusion, curve sweep, array, boolean cut, panel inset, decal plane, UV processing, and LOD
generation may be added only when a benchmark requires them and focused tests cover them.

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

The first implementation task is an armored-vehicle blockout using rounded boxes and cylinders,
with one collider, one pivot, two sockets, one reduced LOD, GLB export, and manifest generation.
