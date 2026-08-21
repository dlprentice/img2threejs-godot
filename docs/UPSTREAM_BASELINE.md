# Upstream baseline

This document records the exact starting point for the Blender/Godot asset-forge experiment. It
does not declare either game ready to consume this fork.

## Repository identity

| Field | Value |
| --- | --- |
| Upstream repository | `img2threejs/img2threejs` |
| Fork repository | `dlprentice/img2threejs-godot` |
| Local path | `C:\Users\david\source\img2threejs-godot` |
| Upstream default branch | `main` |
| Baseline commit | `d6673386f89673a58736f8d398dd16ece67874f5` |
| Baseline commit date | `2026-08-06T12:23:34+07:00` |
| Baseline commit subject | `v1.5 beta — character track, material pipeline, and a release path that actually runs (#75)` |
| Baseline captured | `2026-08-20T20:12:48.8718586-04:00` (`2026-08-21T00:12:48.8718586Z`) |
| Working branch | `feat/blender-godot-asset-forge` |

The fork and upstream both resolved `main` to the baseline commit at capture time.

## Release and version evidence

- Git describes the baseline as `v1.5-beta`; the `v1.5-beta` tag resolves to the baseline commit.
- GitHub's latest release was `v1.5-beta`, published `2026-08-06T11:40:47Z`, targeting `main`.
- Repository-facing version markers are not aligned with that release: `SKILL.md` and the README
  badge say `1.4.4`, while the newest changelog heading is `1.4.4-beta.2`.
- Newly authored sculpt specs use `schemaVersion: "2.1"` in
  `forge/stage2_spec/new_sculpt_spec.py`; `grimoire/scripts.md` still calls the starter schema
  `2.0`.

These values are recorded rather than normalized in this bootstrap so upstream synchronization
remains reviewable.

## License and notices

- SPDX identifier: `Apache-2.0`.
- Required license file present: `LICENSE`.
- The license appendix identifies `Copyright 2026 hoainho`.
- No `NOTICE` or `COPYING` file exists at this baseline. If upstream adds a `NOTICE`, it must be
  preserved in this fork and any distributed derivative.

## Toolchain captured with the baseline

| Tool | Version |
| --- | --- |
| Operating system | Microsoft Windows 11 Home, `10.0.26200`, 64-bit |
| Shell | PowerShell Core `7.6.4` |
| Git | `2.55.0.windows.4` |
| Python | `3.14.2` |
| Node.js | `v24.18.0` |
| npm | `11.17.0` |
| GitHub CLI | `2.92.0` |

The deterministic `forge/` core declares Python 3.10+ standard-library support. Optional vision
adapters have a separate Python `>=3.11,<3.13` environment and therefore are not compatible with
the captured Python 3.14 runtime without a separate interpreter.

## Remotes

```text
origin   https://github.com/dlprentice/img2threejs-godot.git
upstream https://github.com/img2threejs/img2threejs.git
```

Both fetch and push URLs have these values. Only the feature branch may be pushed to `origin` for
this bootstrap; no upstream push or default-branch merge is authorized.

## Reproducing the checkout

From PowerShell, with an authenticated GitHub CLI session:

```powershell
gh repo clone dlprentice/img2threejs-godot C:\Users\david\source\img2threejs-godot
git -C C:\Users\david\source\img2threejs-godot remote set-url origin https://github.com/dlprentice/img2threejs-godot.git
git -C C:\Users\david\source\img2threejs-godot remote add upstream https://github.com/img2threejs/img2threejs.git
git -C C:\Users\david\source\img2threejs-godot fetch --prune origin
git -C C:\Users\david\source\img2threejs-godot fetch --prune upstream
git -C C:\Users\david\source\img2threejs-godot switch -c feat/blender-godot-asset-forge d6673386f89673a58736f8d398dd16ece67874f5
```

If `upstream` already exists, use `remote set-url` instead of `remote add`. Verify before work:

```powershell
git -C C:\Users\david\source\img2threejs-godot remote -v
git -C C:\Users\david\source\img2threejs-godot rev-parse HEAD
git -C C:\Users\david\source\img2threejs-godot status --short --branch
```
