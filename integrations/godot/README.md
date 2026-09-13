# Godot integration

Native tools for Godot 4.7.2: a standalone motion preview and the retained isolated vehicle validator.

## Preview an animated GLB

`preview_motion.py` opens one self-contained GLB in an isolated native Godot scene. It lists imported clips
and skeletons, or captures a selected animation to fixed 1280×720 PNGs. It needs Python and standard Godot;
it does not load a game's project, run an editor import, or require a Factory manifest or workflow.

From this repository, first discover the imported names:

```bash
python3 integrations/godot/preview_motion.py /path/to/character.glb --output local-data/clip-list
```

Then select a clip and, optionally, a bone for the camera to follow. Use the names in the listing:

```bash
python3 integrations/godot/preview_motion.py /path/to/character.glb \
  --animation Walk --follow-bone Hips --duration 4 --fps 30 \
  --camera-center 0,1,0 --camera-offset 4,2,6 --ortho-size 3.5 \
  --output local-data/walk-preview
```

The fixed camera targets `--camera-center`; following adds the chosen bone's displacement from frame zero
to that target. Neither mode edits the model or removes root motion. Camera size is an explicit vertical
span in source units, with no automatic animated-bounds claim. Inspect the framing and adjust it for the
asset. The floor is at Y=-0.005 with a one-unit grid extending ±100 units. Imported transforms and materials
are retained. `--loop source` preserves imported playback and holds the final pose of non-looping clips;
`--loop linear` or `--loop ping-pong` explicitly override playback for seam inspection. The record identifies
both the source mode and the requested override, without changing the input GLB. Multiple players or matching skeletons
need `--player-path` or `--skeleton-path`, as reported in the listing.

The default is four seconds at 30 FPS through Forward+. `--rendering-method gl_compatibility` selects the
Compatibility renderer. `--godot`, then `GODOT_EXECUTABLE`, then PATH select the executable. The default
native timeout is 180 seconds; cancellation uses the existing bounded process-group cleanup. The output
directory must be new. It retains the isolated project and input copy, logs, `preview.json`, and frames;
the record identifies source hash, actual renderer, camera, clip timestamps and decoded PNG hashes.

Playback advances the native animation at fixed intervals. Frame zero samples time zero; the frame count
is `ceil(duration × fps)`, so the last output timestamp is `(count - 1) / fps`. Optional encoding uses an
existing FFmpeg installation, matching the capture FPS:

```bash
ffmpeg -n -framerate 30 -i local-data/walk-preview/frame-%05d.png \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart local-data/walk-preview.mp4
```

This is asset playback for inspection. It does not establish foot planting, collisions, blend transitions,
gameplay suitability, editor texture/LOD import equivalence or real-time performance. Review the resulting
motion and the consuming game's actual import before adoption. External GLB resources are unsupported;
embed buffers/textures first. Ordinary provenance URLs in glTF `extras` are preserved.

## Retained vehicle validator

The integration consumes a validated GLB and `asset_manifest.json` in an isolated validation
project. Godot's imported scene and review render establish the checked technical behavior;
artistic acceptance belongs to the consuming game in its actual gameplay context.

## Responsibilities

- Build a new temporary project per attempt from only `project.godot`, `main.gd`, and `main.tscn`.
- Correlate outputs to the attempt, GLB hash, input-manifest hash, and a generated nonce.
- Preserve import/render stdout and stderr; fail errors and non-allowlisted warnings.
- Verify metric scale, bounds, forward/up axes, ground placement, hierarchy, local/world transforms,
  material bindings, socket and pivot transforms, collision raycast behavior, and explicit LOD switching.
- Render the RTS view, a stage-only baseline, an isolated asset mask, and per-component visibility probes.
- Decode, freshness-check, and hash every accepted PNG before copying it into attempt evidence.
- Emit a machine-readable packaging/validation result and actual import diagnostics for the manifest.

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

```bash
python3 integrations/godot/run_validation.py --artifact-dir /absolute/path/to/artifact
```

The runner uses `--godot` when supplied, then `GODOT_EXECUTABLE`, then `godot` on PATH. This
GDScript validation project uses the standard Godot build. Temporary projects live under `/var/tmp`
and are removed on exit; completed outputs stay in the supplied artifact directory. The viewport
renders at 960x540 even when a tiling compositor resizes the window.

Native execution uses the shared bounded cleanup in `backends/process.py`. On POSIX the runner owns the
tool's process group and propagates main-thread cancellation to it; inherited output pipes cannot turn
timeout cleanup into an unbounded wait. This is trusted-tool lifecycle management, not a sandbox for
deliberately detached processes. See the Python-only checks in `backends/blender/tests/test_process.py`.

The runner copies only the required inputs into a newly created disposable validation project, performs a Godot
editor import pass, then renders through Forward+ to `rts.png`. It verifies required mesh, pivot,
socket, collider, and LOD semantics; exercises both LOD levels; records renderer and adapter
identity, draw calls, CPU frame samples, and asset-specific pixel metrics; and fails when the asset
or any mandatory component contributes insufficient visible pixels.

Godot 4.7.1's official runtime exposed no `RenderingDevice` GPU timestamp samples in the benchmark
environment. The report therefore records GPU timing as explicitly unavailable rather than
substituting CPU time. Host-wide GPU-memory sampling belongs to the private scheduler, not this
generic adapter.

The current implementation validates one generic RTS hard-surface profile and uses an explicit
wrapper visibility policy for LOD switching rather than Godot distance-based LOD. Graph v0 rejects
nonzero pivot origins instead of claiming arbitrary-pivot support. It does not install an
asset into a game, add gameplay behavior, or claim support for isometric, organic, rigged, textured,
or destructible assets.
