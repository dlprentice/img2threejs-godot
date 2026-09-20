# img2threejs-godot: agent guide

Read this before changing anything. It is the only instruction file in the repo; `CLAUDE.md` just points here.
Read [folder rules](../AGENTS.md), [project-tree rules](../../AGENTS.md), and [machine rules](../../../AGENTS.md) first.
Machine-wide rules are in `~/AGENTS.md`; the folder rules are in `~/Projects/game-dev/AGENTS.md`.

## What this is

David's fork of `img2threejs/img2threejs` (remote `upstream`; `origin` is `dlprentice/img2threejs-godot`, branch
`main`) and the canonical source for the `img2threejs` skill: `forge/` is the deterministic staged tooling (intake,
spec, build, review, rig; tests in `forge/tests/`), `grimoire/` the routed reference material, and `SKILL.md`,
`README.md`, `CHANGELOG.md` and `ROADMAP.md` the release-facing documents. David's additions on top of upstream are
`backends/blender/` (the headless Blender backend), `integrations/godot/` (the Godot validation harness), `schemas/`,
`LICENSES/` and `MIXED_LICENSES.md`. The Factory reference benchmark uses the Blender/validation route;
`integrations/godot/preview_motion.py` also provides direct GLB inspection without Factory or a game project. The upstream
branches mirrored on `origin` stay: never delete branches here. Retain the fork without expanding its platform;
use the native backends only when a concrete task benefits. Do not create an extraction project merely to reduce
repository size. The upstream Three.js workflow is optional, not a prerequisite for making Godot game assets.

Agent tool homes are application-owned state. Manage skill installation through the owning application;
do not create links or synchronize those homes from this repository.

## Change rules

- Preserve the code-only contract when working on procedural Three.js reconstruction; do not silently substitute
  downloaded meshes or art packs. It does not restrict a consuming game's separately authorized asset choices.
- Keep claims honest: distinguish implemented capability from roadmap or design-only documentation.
- Treat `forge/` as deterministic tooling and `grimoire/` as routed reference material.
- Put new captures, review comparisons and machine-local inputs in ignored `local-data/`; retained `work/`
  and `.screenshot/` consumers remain unchanged until a deliberate migration is authorized.
- Keep backward compatibility for existing sculpt specs unless a migration is explicitly planned.
- When changing schema, gates, generators, or review behavior, add or update focused tests.
- Keep `SKILL.md`, `README.md`, `CHANGELOG.md`, and `ROADMAP.md` consistent when release-facing
  behavior changes.
- Reference the companion showcase through `IMG2THREEJS_SHOWCASE_ROOT`, never an absolute path; a
  path that only exists on one machine passes there and fails everywhere else, CI included.

## Verification

For prose/instruction-only changes, review the complete diff and touched local links, run `git diff --check`
and the affected router/release-metadata checks. For code changes, start with the affected existing tests;
the complete command below is for cross-cutting work or release, not every edit.

```bash
python3 -m unittest discover -s forge/tests -p 'test_*.py'
```

Set `IMG2THREEJS_SHOWCASE_ROOT` to a showcase checkout to include the TypeScript typecheck gates;
without it they skip, and a green run has not proven the emitted Three.js compiles. Add
`IMG2THREEJS_REQUIRE_SHOWCASE=1` to turn that skip into a failure.

Do not report completion without reading the fresh outputs. For visual reconstruction changes,
structural tests and screenshot/reference-loop validation are separate required gates.

## Visual review

Inspect the output through its intended renderer at the intended dimensions and camera. Save and open the
relevant captures in `local-data/`; inspect motion or extra angles when needed for the claim. Compare with the
reference and fix visible defects. Structural tests and image scores cannot establish taste or replace looking.
If capture fails, repair it before making visual claims; do not infer a pass from code or runtime readiness.

An existing staged Three.js reconstruction keeps its executable pass/review contracts; use `SKILL.md` to route
to their references. Native Blender/Godot tasks do not inherit the entire Three.js scoring and browser workflow.
No authentication check, repeated comparison matrix or critic panel is required for unrelated maintenance.

## Gotchas

- Both Godot runners resolve `--godot`, then `GODOT_EXECUTABLE`, then `godot-dev`, then `godot` on PATH.
  The shared development alias currently selects 4.8 dev6 standard; explicit executable paths can select
  a consumer's standard or .NET build. No Factory registry or script change is needed to test another engine.
  The validator's disposable project uses `/var/tmp`; its 960x540 viewport is independent of compositor window
  sizing. `../game-asset-factory`'s benchmark calls the shared native `validate-gltf.sh` entrypoint.
