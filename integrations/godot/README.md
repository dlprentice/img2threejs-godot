# Godot integration contract

Status: design scaffold only. No Godot importer or scene generator is implemented by this
bootstrap.

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
