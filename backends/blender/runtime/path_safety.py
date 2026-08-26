from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def safe_asset_path(asset_root: Path, relative_path: str) -> Path:
    """Resolve a manifest path without permitting an escape from the asset root."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("artifact path must be a non-empty string")
    if "\\" in relative_path:
        raise ValueError("artifact paths must use forward slashes")
    posix = PurePosixPath(relative_path)
    windows = PureWindowsPath(relative_path)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        raise ValueError(f"unsafe artifact path: {relative_path!r}")
    root = asset_root.expanduser().resolve()
    candidate = root.joinpath(*posix.parts).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"artifact path escapes asset root: {relative_path!r}")
    return candidate
