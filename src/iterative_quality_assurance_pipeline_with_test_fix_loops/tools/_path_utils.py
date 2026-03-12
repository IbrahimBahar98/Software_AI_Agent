"""Shared path normalization utilities for all workspace tools."""
import os
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR, WORKSPACE_DIR


def normalize_workspace_path(file_path: str, base_dir: str = None) -> str:
    """Normalize a file path to be safely within the workspace.

    Handles:
    - Absolute paths that include the workspace/repo prefix
    - Relative paths with redundant workspace/repo prefixes
    - Windows backslashes
    - Dotfiles (preserves leading dots)

    Returns the full absolute path within base_dir.
    """
    if base_dir is None:
        base_dir = REPO_DIR

    # Normalize separators
    clean = file_path.replace("\\", "/")

    # Handle absolute paths
    if os.path.isabs(clean) or (len(clean) > 1 and clean[1] == ':'):
        norm = os.path.normpath(clean)
        abs_base = os.path.abspath(base_dir)
        if norm.startswith(abs_base):
            clean = os.path.relpath(norm, abs_base)
        else:
            for marker in ["/workspace/repo/", "/workspace/", "/repo/"]:
                idx = clean.find(marker)
                if idx != -1:
                    clean = clean[idx + len(marker):]
                    break
            else:
                clean = os.path.relpath(norm, abs_base) if norm.startswith(abs_base) else clean

    # Remove leading ./ (but NOT single dots that are part of filenames)
    if clean.startswith("./"):
        clean = clean[2:]

    # Strip known workspace prefixes (order matters — longest first)
    prefixes = ["workspace/repo/", "workspace/", "repo/"]
    for prefix in prefixes:
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break

    clean = clean.strip("/")

    full_path = os.path.normpath(os.path.join(base_dir, clean))
    return full_path


def validate_path_in_workspace(
    full_path: str,
    base_dir: str = None,
    allow_workspace_parent: bool = False,
) -> bool:
    """Ensure the resolved path doesn't escape the workspace.

    Args:
        full_path: The path to validate.
        base_dir: The base directory to check against. Defaults to REPO_DIR.
        allow_workspace_parent: If True, also allows paths within WORKSPACE_DIR
                                (e.g., for QA_REPORT.md written to repo/../).
    """
    if base_dir is None:
        base_dir = REPO_DIR

    abs_target = os.path.abspath(full_path)

    # Check against base_dir first
    abs_base = os.path.abspath(base_dir)
    if abs_target.startswith(abs_base + os.sep) or abs_target == abs_base:
        return True

    # Optionally allow WORKSPACE_DIR (parent of REPO_DIR)
    if allow_workspace_parent:
        abs_workspace = os.path.abspath(WORKSPACE_DIR)
        if abs_target.startswith(abs_workspace + os.sep) or abs_target == abs_workspace:
            return True

    return False