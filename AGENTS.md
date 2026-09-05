# img2threejs-godot: agent guide

Read this before changing anything. It is the only instruction file in the repo; `CLAUDE.md` just points here.
Machine-wide rules are in `~/AGENTS.md`; the folder rules are in `~/Projects/game-dev/AGENTS.md`.

## What this is

David's fork of `img2threejs/img2threejs` (remote `upstream`; `origin` is `dlprentice/img2threejs-godot`, branch
`main`) and the canonical source for the `img2threejs` skill: `forge/` is the deterministic staged tooling (intake,
spec, build, review, rig; tests in `forge/tests/`), `grimoire/` the routed reference material, and `SKILL.md`,
`README.md`, `CHANGELOG.md` and `ROADMAP.md` the release-facing documents. David's additions on top of upstream are
`backends/blender/` (the headless Blender backend), `integrations/godot/` (the Godot validation harness), `schemas/`,
`LICENSES/` and `MIXED_LICENSES.md`; `../game-asset-factory`'s `benchmark` is their only consumer. The upstream
branches mirrored on `origin` stay: never delete branches here. Keeping the whole fork or extracting the additions
into a small repo of David's own is his open decision (`~/Projects/game-dev/PLAN.md` section 4).

The host entrypoints `~/.claude/skills/img2threejs` and `~/.codex/skills/img2threejs` are absent after the Omarchy
migration. If the skill is installed later, both entrypoints must be symlinks to this one checkout, never
independent copies, or the hosts will drift.

## Change rules

- Preserve the code-only procedural Three.js contract; do not silently download meshes or art packs.
- Keep claims honest: distinguish implemented capability from roadmap or design-only documentation.
- Treat `forge/` as deterministic tooling and `grimoire/` as routed reference material.
- Keep backward compatibility for existing sculpt specs unless a migration is explicitly planned.
- When changing schema, gates, generators, or review behavior, add or update focused tests.
- Keep `SKILL.md`, `README.md`, `CHANGELOG.md`, and `ROADMAP.md` consistent when release-facing
  behavior changes.
- Reference the companion showcase through `IMG2THREEJS_SHOWCASE_ROOT`, never an absolute path; a
  path that only exists on one machine passes there and fails everywhere else, CI included.

## Verification

```bash
python3 -m unittest discover -s forge/tests -p 'test_*.py'
```

Set `IMG2THREEJS_SHOWCASE_ROOT` to a showcase checkout to include the TypeScript typecheck gates;
without it they skip, and a green run has not proven the emitted Three.js compiles. Add
`IMG2THREEJS_REQUIRE_SHOWCASE=1` to turn that skip into a failure.

Do not report completion without reading the fresh outputs. For visual reconstruction changes,
structural tests and screenshot/reference-loop validation are separate required gates.

## Mandatory visual screenshot gate

For every visual reconstruction task, a readable screenshot is a hard prerequisite for visual
implementation claims and completion:

1. Before accepting visual results, verify that the browser/screenshot tooling is installed,
   authenticated, reachable, and able to capture the running showcase.
2. Save fresh PNG/JPEG screenshots inside the workspace, including the fixed reference view and the
   required orbit views. Inline previews alone are not evidence.
3. Read the saved screenshots back with an image-capable tool and verify they contain the rendered
   model at the expected dimensions. A screenshot that cannot be opened or visually read is a failed
   gate.
4. Produce and retain a side-by-side reference/render comparison, semantic image scoring,
   pixel/feature comparison, and the `forge/stage4_review/diagnose_render.py` output for the saved
   render before reporting visual validation.
5. If capture, file write, readback, comparison, scoring, or diagnosis fails, stop the visual
   workflow and repair the tooling first. Do not infer visual evidence from runtime readiness,
   structural tests, inline previews, or code review, and do not claim the visual gate passed.

## Gotchas

- `integrations/godot/run_validation.py` defaults (line 26) to `C:\Tools\Godot\bin\Godot_console.exe`; it takes
  `--godot` but has no `GODOT_EXECUTABLE` fallback, and `../game-asset-factory`'s `benchmark.py` runs
  `validate-gltf.ps1` through `pwsh`, so the cross-repo route does not complete on Linux yet
  (`~/Projects/game-dev/PLAN.md` 3.2). The Windows default is history, not routing.
