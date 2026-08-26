# Full campaign handoff

The generic Blender/Godot hard-surface implementation remains on this public branch. The rest of the six-milestone campaign is intentionally split across private control and game-integration branches so no private art bible or project policy enters this fork.

## Related submissions

| Repository | Branch | Commit | Purpose |
|---|---|---|---|
| `dlprentice/img2threejs-godot` | `feat/milestones-1-6-complete` | this branch | Generic constrained spec → Blender → GLB/manifest → Godot validation, plus bundled license texts |
| `dlprentice/game-asset-factory` | `feat/milestones-2-6-complete` | `d21c9d90d4fbcac2214d853191aba7b9562f044f` | Complete private control plane, catalog, materials, audio, model batch, animation, worlds, UI/VFX, slices, attestations, and adapters |
| `dlprentice/ultra_commander` | `feat/agentic-asset-factory-integration` | `9161be765e595092af33ed9a6299c0bca552331f` | Isolated RTS smoke slice; default runtime unchanged |
| `dlprentice/zombie_defense` | `feat/agentic-asset-factory-integration` | `e106161826896f92b1f1f51b9c8f5646025c3741` | Isolated isometric-zombie smoke slice; default runtime unchanged |

No default branch is merged. No GitHub Actions workflow or GitHub-hosted runner minute is used. Hardware-dependent acceptance remains a local Codex workstation gate after the software campaign implementation.

The deterministic reference assets prove the pipelines and contracts. They are not presented as final production art or as evidence that gated/open-weight model adapters have already run.