from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess
import os
import tempfile
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._path_utils import (
    normalize_workspace_path, validate_path_in_workspace
)


class PatchApplyInput(BaseModel):
    """Input schema for Patch Apply Tool."""
    file_path: str = Field(..., description="Path to the file to patch (relative or absolute).")
    patch_content: str = Field(..., description="The unified diff / patch content to apply.")


class PatchApplyTool(BaseTool):
    """Tool for applying unified diff patches to local workspace files."""

    name: str = "patch_apply_tool"
    description: str = (
        "Applies a unified diff patch to a file. Provide the 'file_path' and "
        "'patch_content' (the diff). Tries 'patch' command first, falls back to "
        "'git apply'. This is safer than overwriting entire files for small edits. "
        "If this fails, use file_write_tool to overwrite the file instead."
    )
    args_schema: Type[BaseModel] = PatchApplyInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _run(self, file_path: str, patch_content: str) -> str:
        """Apply a patch to a file in the workspace."""
        try:
            full_path = normalize_workspace_path(file_path, self.workspace_dir)

            if not validate_path_in_workspace(full_path, self.workspace_dir):
                return json.dumps({
                    "success": False,
                    "error": f"Path '{file_path}' resolves outside the workspace."
                })

            if not os.path.exists(full_path):
                return json.dumps({
                    "success": False,
                    "error": f"File '{file_path}' does not exist. Use file_write_tool to create new files."
                })

            # Create temp file for patch content
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.patch', encoding='utf-8') as tmp:
                tmp.write(patch_content)
                temp_patch_path = tmp.name

            try:
                # Strategy 1: patch command (specific file, no strip)
                result = subprocess.run(
                    ["patch", full_path],
                    input=patch_content,
                    text=True,
                    capture_output=True,
                    cwd=self.workspace_dir,
                    timeout=30
                )

                if result.returncode == 0:
                    return json.dumps({
                        "success": True,
                        "message": f"Successfully applied patch to '{file_path}'",
                        "log": result.stdout[:2000]
                    })

                # Strategy 2: git apply with whitespace tolerance
                result_git = subprocess.run(
                    ["git", "apply", "--ignore-whitespace", "--verbose", temp_patch_path],
                    capture_output=True,
                    text=True,
                    cwd=self.workspace_dir,
                    timeout=30
                )
                if result_git.returncode == 0:
                    return json.dumps({
                        "success": True,
                        "message": f"Successfully applied git patch to '{file_path}'",
                        "log": result_git.stdout[:2000]
                    })

                # Strategy 3: git apply with extra tolerance
                result_git3 = subprocess.run(
                    ["git", "apply", "--ignore-whitespace", "--3way", temp_patch_path],
                    capture_output=True,
                    text=True,
                    cwd=self.workspace_dir,
                    timeout=30
                )
                if result_git3.returncode == 0:
                    return json.dumps({
                        "success": True,
                        "message": f"Applied patch to '{file_path}' via 3-way merge",
                        "log": result_git3.stdout[:2000]
                    })

                return json.dumps({
                    "success": False,
                    "error": (
                        "Patch failed to apply. Common causes:\n"
                        "1. Line numbers in @@ headers don't match current file\n"
                        "2. Missing --- a/file and +++ b/file headers\n"
                        "3. Context lines don't match (file changed since diff was created)\n"
                        "TIP: Use file_write_tool to overwrite the entire file instead."
                    ),
                    "patch_stderr": result.stderr[:2000],
                    "git_stderr": result_git.stderr[:2000]
                })

            finally:
                if os.path.exists(temp_patch_path):
                    os.unlink(temp_patch_path)

        except subprocess.TimeoutExpired:
            return json.dumps({"success": False, "error": "Patch command timed out after 30 seconds."})
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to patch file '{file_path}': {str(e)}"
            })
