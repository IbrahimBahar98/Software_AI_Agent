"""
Patch apply tool for the QA pipeline.
Applies unified diffs to files. Falls back through multiple strategies.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess
import shutil
import platform
import os
import tempfile
import json
import logging
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR, WORKSPACE_DIR
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._path_utils import (
    normalize_workspace_path, validate_path_in_workspace
)

logger = logging.getLogger(__name__)
IS_WINDOWS = platform.system() == "Windows"


class PatchApplyInput(BaseModel):
    """Input schema for Patch Apply Tool."""
    file_path: str = Field(
        ..., description="Path to the file to patch (relative or absolute)."
    )
    patch_content: str = Field(
        ..., description="The unified diff / patch content to apply."
    )


class PatchApplyTool(BaseTool):
    """Tool for applying unified diff patches to workspace files."""

    name: str = "patch_apply_tool"
    description: str = (
        "Applies a unified diff patch to a file. Provide 'file_path' and "
        "'patch_content' (the diff). Tries multiple strategies: "
        "1) git apply, 2) patch command (Unix only), 3) Python fallback. "
        "If all fail, use file_write_tool to overwrite the file instead."
    )
    args_schema: Type[BaseModel] = PatchApplyInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

    def _exec(self, cmd, cwd: str, input_text: str = None, timeout: int = 30):
        """Run a command and return (success, stdout, stderr)."""
        try:
            result = subprocess.run(
                cmd, cwd=cwd, input=input_text,
                capture_output=True, text=True, timeout=timeout
            )
            return (
                result.returncode == 0,
                result.stdout[:2000],
                result.stderr[:2000],
            )
        except subprocess.TimeoutExpired:
            return False, "", "Timed out"
        except FileNotFoundError:
            return False, "", f"Command not found: {cmd[0]}"
        except Exception as e:
            return False, "", str(e)

    def _try_git_apply(self, patch_path: str, cwd: str) -> tuple:
        """Try git apply with increasing tolerance."""
        if not shutil.which("git"):
            return False, "", "git not found on PATH"

        strategies = [
            ["git", "apply", "--verbose", patch_path],
            ["git", "apply", "--ignore-whitespace", "--verbose", patch_path],
            ["git", "apply", "--ignore-whitespace", "--3way", patch_path],
        ]

        last_stderr = ""
        for cmd in strategies:
            ok, stdout, stderr = self._exec(cmd, cwd)
            if ok:
                return True, stdout, ""
            last_stderr = stderr

        return False, "", last_stderr

    def _try_patch_command(self, full_path: str, patch_content: str, cwd: str) -> tuple:
        """Try the patch command (Unix only)."""
        if IS_WINDOWS:
            return False, "", "patch command not available on Windows"
        if not shutil.which("patch"):
            return False, "", "patch command not found"

        return self._exec(
            ["patch", full_path],
            cwd=cwd,
            input_text=patch_content,
        )

    def _try_python_fallback(self, full_path: str, patch_content: str) -> tuple:
        """
        Simple Python-based patch applier for single-file patches.
        Only handles basic unified diffs (one hunk, add/remove lines).
        """
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                original_lines = f.readlines()

            # Parse patch hunks
            hunks = []
            current_hunk = None
            for line in patch_content.split('\n'):
                if line.startswith('@@'):
                    # Parse @@ -start,count +start,count @@
                    import re
                    match = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                    if match:
                        current_hunk = {
                            'old_start': int(match.group(1)) - 1,  # 0-indexed
                            'lines': [],
                        }
                        hunks.append(current_hunk)
                elif current_hunk is not None:
                    if line.startswith('+') and not line.startswith('+++'):
                        current_hunk['lines'].append(('add', line[1:]))
                    elif line.startswith('-') and not line.startswith('---'):
                        current_hunk['lines'].append(('remove', line[1:]))
                    elif line.startswith(' '):
                        current_hunk['lines'].append(('context', line[1:]))

            if not hunks:
                return False, "", "No valid hunks found in patch"

            # Apply hunks in reverse order to preserve line numbers
            result_lines = list(original_lines)
            for hunk in reversed(hunks):
                offset = hunk['old_start']
                new_lines = []
                idx = offset
                for action, content in hunk['lines']:
                    if action == 'context':
                        idx += 1
                    elif action == 'remove':
                        idx += 1
                    elif action == 'add':
                        new_lines.append(content + '\n')

                # Simple replacement: remove old range, insert new
                remove_count = sum(1 for a, _ in hunk['lines'] if a in ('context', 'remove'))
                insert_lines = []
                for action, content in hunk['lines']:
                    if action in ('context', 'add'):
                        insert_lines.append(content + '\n')

                result_lines[offset:offset + remove_count] = insert_lines

            with open(full_path, 'w', encoding='utf-8') as f:
                f.writelines(result_lines)

            return True, "Applied via Python fallback", ""

        except Exception as e:
            return False, "", f"Python fallback failed: {e}"

    def _run(self, file_path: str, patch_content: str) -> str:
        """Apply a patch to a file in the workspace."""
        temp_patch_path = None
        try:
            full_path = normalize_workspace_path(file_path, self.workspace_dir)

            if not validate_path_in_workspace(
                full_path, self.workspace_dir, allow_workspace_parent=False
            ):
                return json.dumps({
                    "success": False,
                    "error": f"Path '{file_path}' resolves outside the workspace."
                })

            if not os.path.exists(full_path):
                return json.dumps({
                    "success": False,
                    "error": (
                        f"File '{file_path}' does not exist. "
                        "Use file_write_tool to create new files."
                    )
                })

            # Write patch to temp file for git apply
            with tempfile.NamedTemporaryFile(
                'w', delete=False, suffix='.patch', encoding='utf-8'
            ) as tmp:
                tmp.write(patch_content)
                temp_patch_path = tmp.name

            # Strategy 1: git apply (most reliable)
            ok, stdout, stderr = self._try_git_apply(temp_patch_path, self.workspace_dir)
            if ok:
                return json.dumps({
                    "success": True,
                    "method": "git apply",
                    "message": f"Successfully applied patch to '{file_path}'",
                    "log": stdout,
                })

            # Strategy 2: patch command (Unix)
            ok, stdout, stderr_patch = self._try_patch_command(
                full_path, patch_content, self.workspace_dir
            )
            if ok:
                return json.dumps({
                    "success": True,
                    "method": "patch",
                    "message": f"Successfully applied patch to '{file_path}'",
                    "log": stdout,
                })

            # Strategy 3: Python fallback (basic diffs only)
            ok, stdout, stderr_py = self._try_python_fallback(full_path, patch_content)
            if ok:
                return json.dumps({
                    "success": True,
                    "method": "python_fallback",
                    "message": f"Applied patch to '{file_path}' (Python fallback)",
                    "log": stdout,
                })

            # All strategies failed
            return json.dumps({
                "success": False,
                "error": (
                    "Patch failed with all strategies.\n"
                    "Common causes:\n"
                    "1. Line numbers in @@ headers don't match current file\n"
                    "2. Missing --- a/file and +++ b/file headers\n"
                    "3. Context lines don't match (file changed since diff)\n"
                    "TIP: Use file_write_tool to overwrite the entire file."
                ),
                "git_stderr": stderr[:500],
                "patch_stderr": stderr_patch[:500],
                "python_stderr": stderr_py[:500],
            })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Patch failed: {type(e).__name__}: {e}"
            })
        finally:
            if temp_patch_path and os.path.exists(temp_patch_path):
                try:
                    os.unlink(temp_patch_path)
                except Exception:
                    pass