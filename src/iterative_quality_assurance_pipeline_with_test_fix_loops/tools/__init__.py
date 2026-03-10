"""QA Pipeline Tools Package.

Provides workspace-locked tools for file I/O, bash execution,
GitHub operations, MCP bridge, linting, testing, and checkpointing.
All tools auto-detect multi-language projects.
"""

from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages,
    detect_test_framework,
    build_project_profile,
    ProjectProfile,
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._path_utils import (
    normalize_workspace_path,
    validate_path_in_workspace,
)

__all__ = [
    "detect_languages",
    "detect_test_framework",
    "build_project_profile",
    "ProjectProfile",
    "normalize_workspace_path",
    "validate_path_in_workspace",
]