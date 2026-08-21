# Godot integration

Status: experimental isolated validator implemented and benchmarked with Godot 4.7.1.

The integration consumes a validated GLB and `asset_manifest.json` in an isolated validation
project. Godot's imported scene and gameplay-camera render are the final technical and visual
authority.

## Responsibilities

- Import GLB and capture every warning and error.
- Verify metric scale, bounds, forward/up axes, ground placement, hierarchy, and material bindings.
- Generate an inherited scene when possible, otherwise a minimal wrapper scene.
- Map collision records, LODs, pivots, and sockets to stable Godot nodes/resources.
- Support declarative faction material overrides and VFX scene attachment by generic role.
- Apply navigation metadata without embedding game-specific navigation layers in this public fork.
- Produce neutral, RTS, and isometric preview scenes with versioned camera/render profiles.
- Capture rendering correctness, draw calls, and frame-time evidence.
- Emit a machine-readable packaging/validation result for the manifest.

## Boundaries

- Do not copy code, assets, prompts, art bibles, or resource paths from a game repository.
- Do not add gameplay behavior to generated wrappers.
- Never infer a missing socket, collision shape, LOD, or material silently; fail or report an
  explicit unsupported/repair result.
- Visual approval cannot override a GLB, import, transform, collision, LOD, texture, or budget gate.
- All generated paths are relative and all generated node names derive from stable manifest IDs.

Private project tooling may map generic roles such as `selection_origin`, `primary_weapon`,
`muzzle_vfx`, `faction_surface`, and `navigation_obstacle` to a game's conventions after the public
benchmark gate passes.

## Run the isolated proof

Given an artifact directory containing `asset.glb` and `asset_manifest.json`:

```powershell
python integrations/godot/run_validation.py --artifact-dir runtime/armored-vehicle
```

The runner copies only the required inputs into a disposable validation project, performs a Godot
editor import pass, then renders through Forward+ to `rts.png`. It verifies required mesh, pivot,
socket, collider, and LOD identifiers; hides the far-LOD meshes for the near view; records renderer
and adapter identity, draw calls, CPU frame samples, and image-content metrics; and fails a blank or
low-contrast capture.

Godot 4.7.1's official runtime exposed no `RenderingDevice` GPU timestamp samples in the benchmark
environment. The report therefore records GPU timing as explicitly unavailable rather than
substituting CPU time. Host-wide GPU-memory sampling belongs to the private scheduler, not this
generic adapter.

The current implementation validates one generic RTS hard-surface profile. It does not install an
asset into a game, add gameplay behavior, or claim support for isometric, organic, rigged, textured,
or destructible assets.
