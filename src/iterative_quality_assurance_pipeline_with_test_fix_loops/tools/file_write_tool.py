"""
File write tool for the QA pipeline.
Writes content to files within or near the workspace.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_FILE_WRITE_BYTES, WORKSPACE_DIR
)


class FileWriteInput(BaseModel):
    """Input schema for File Write Tool."""
    file_path: str = Field(..., description="Path to the file to create/overwrite (relative or absolute).")
    content: str = Field(..., description="The complete file content to write.")


class FileWriteTool(BaseTool):
    """Tool for writing content to files in the workspace."""

    name: str = "file_write_tool"
    description: str = (
        "Writes content to a file. Provide file_path (relative like 'src/main.py' "
        "or absolute) and full content. Parent directories are created automatically. "
        "Overwrites if file exists. Can write to repo directory and parent workspace."
    )
    args_schema: Type[BaseModel] = FileWriteInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

    def _normalize_path(self, file_path: str) -> str:
        """Normalize file_path to absolute, handling relative and absolute inputs."""
        file_path = file_path.strip().strip('"').strip("'")

        if os.path.isabs(file_path):
            return os.path.normpath(file_path)

        return os.path.normpath(os.path.join(self.workspace_dir, file_path))

    def _validate_path(self, full_path: str) -> bool:
        """
        Security check: path must be within WORKSPACE_DIR (not just REPO_DIR).
        This allows writing QA_REPORT.md to {repo_abs_path}/../
        which is still inside workspace/.
        """
        # Resolve symlinks and normalize
        try:
            resolved = os.path.realpath(full_path)
            workspace_resolved = os.path.realpath(WORKSPACE_DIR)
            return resolved.startswith(workspace_resolved + os.sep) or resolved == workspace_resolved
        except Exception:
            return False

    def _run(self, file_path: str, content: str) -> str:
        """Write content to a file."""
        try:
            # Size guard
            if len(content) > MAX_FILE_WRITE_BYTES:
                return json.dumps({
                    "success": False,
                    "error": f"Content too large ({len(content)} chars). Max: {MAX_FILE_WRITE_BYTES}"
                })

            full_path = self._normalize_path(file_path)

            # Security: must be within WORKSPACE_DIR (allows parent of REPO_DIR)
            if not self._validate_path(full_path):
                return json.dumps({
                    "success": False,
                    "error": (
                        f"Path '{file_path}' resolves to '{full_path}' which is "
                        f"outside the workspace '{WORKSPACE_DIR}'. "
                        f"Use a path within the workspace."
                    )
                })

            # Create parent directories
            parent_dir = os.path.dirname(full_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Write
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            size = os.path.getsize(full_path)

            # Show relative path for readability
            try:
                rel_path = os.path.relpath(full_path, self.workspace_dir)
            except ValueError:
                rel_path = full_path

            return json.dumps({
                "success": True,
                "message": f"Wrote {size} bytes to '{rel_path}'",
                "absolute_path": full_path,
            })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to write '{file_path}': {type(e).__name__}: {e}"
            })