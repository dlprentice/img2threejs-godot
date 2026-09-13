---
name: img2threejs
description: Reconstruct a reference as a procedural Three.js model using this repo's sculpt-spec pipeline.
license: Apache-2.0
version: 1.4.4
---

# img2threejs — procedural Three.js reconstruction

Use this skill for the requested Three.js reconstruction or an existing sculpt-spec
workflow. It is not a general Godot asset-making policy. Ordinary Blender authoring,
Godot game work, and maintenance of this fork's native backends do not need its
Three.js stages, local-state records or review packets.

Read the repository `AGENTS.md` and the references relevant to the selected route.
Manage installation through the owning application; never create links, copy skills
or synchronize agent tool homes from this repository.

## Choose the actual route

- **Native Blender/Godot backend work:** use `backends/blender/` or
  `integrations/godot/` and their existing checks. The [native integration guide](integrations/godot/README.md)
  includes optional animated-GLB preview and posed surface measurements. Stop reading this router here;
  the consuming game owns art direction and acceptance.
- **Procedural Three.js reconstruction:** preserve the code-only contract. Do not
  silently substitute downloaded meshes, projected detail for missing geometry,
  or an unrelated renderer. Unseen surfaces are inferred, not verified.
- **Existing staged reconstruction:** inspect
  `python3 forge/next.py --state .img2threejs/state.json` (or
  `python3 forge/next.py <spec>` for a spec-only workflow). Honor its real pass,
  correction-limit and spec-identity checks; do not bypass a failed gate by
  deleting state or regenerating over a required code refinement.

This skill does not promise animation, destruction, photorealism or exact likeness
merely because a file was generated. Implement the runtime behavior actually requested.

## References for the selected reconstruction

Use `grimoire/scripts.md` for command syntax and the applicable stage references.
Do not read the entire grimoire for a small change.

- Intake suitability and detail analysis:
  `grimoire/intake/validation_rubric.md` and
  `grimoire/intake/detail_inventory.md`.
- Character work: `grimoire/character/reconstruction.md`; requested likeness work
  additionally uses `grimoire/character/likeness_maximization.md`.
- CS2 workflow: MUST read `grimoire/intake/cs2_intake_contract.md` completely
  before its intake. Use the implemented family contract, not an invented
  approximation presented as exact.
- Existing staged review: MUST read
   `grimoire/review/gates_reference.md` before advancing that workflow's gates.
- Material reference work: `docs/materials/README.md`.
- Browser render integration: `grimoire/build/python_threejs_render_bridge.md`.

The selected references define that route's actual contracts. They do not impose a
campaign, browser integration or scoring stack on unrelated native game work.

## Build, inspect, improve

Start from the reference, intended camera, scale and requested motion. Preserve
the spec's public interfaces and approved part hierarchy. Reuse the existing
generator and validator rather than making a parallel framework.

For a staged job, run its applicable structural and render checks and update its
existing state with genuine results. Relevant review tools include
`forge/stage4_review/diagnose_render.py`,
`forge/stage4_review/diagnose_render_multi_angle.py`, and
`forge/stage4_review/check_part_coverage.py`; choose them through the route's
contract, not as an all-purpose checklist.

Open the actual target-renderer output. Compare silhouette, proportions, materials
and identity-bearing details at the intended view; inspect additional angles or
motion where the claim needs them. A high image score cannot excuse wrong geometry
or missing behavior. Fix the dominant visible problem and inspect again. Do not
repeat unchanged checks or create extra critic panels/status documents by default.

New private inputs and captures belong in ignored `local-data/`. Preserve existing
state, source assets, attribution and evidence; do not relocate retained `work/`
or `.screenshot/` data just to change folder names.

## Completion

Deliver the requested usable artifact, with the affected existing checks passed and
the actual image/motion inspected. For pure tooling or documentation changes, test
the affected behavior or links; no visual campaign is needed. State unresolved
approximation, licence, performance or renderer limits plainly. A successful
generation or schema check is technical evidence, not proof of good art.
