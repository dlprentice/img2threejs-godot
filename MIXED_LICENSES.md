# Mixed-license notice

This repository is not uniformly Apache-2.0.

| Scope | SPDX license | Bundled text |
| --- | --- | --- |
| Repository source except the file listed below | `Apache-2.0` | `LICENSES/Apache-2.0.txt` |
| `backends/blender/runtime/blender_build.py` | `GPL-3.0-or-later` | `LICENSES/GPL-3.0-or-later.txt` |

`blender_build.py` runs inside Blender and carries its own SPDX header and copyright notice.
Generated GLB assets and manifests are not copied source code from that script and retain the output
license recorded in their manifest. The complete license texts are bundled locally so release and
offline consumers do not depend on external links.
