from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR, MAX_FILE_WRITE_BYTES
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._path_utils import (
    normalize_workspace_path, validate_path_in_workspace
)


class FileWriteInput(BaseModel):
    """Input schema for File Write Tool."""
    file_path: str = Field(..., description="Path to the file to create/overwrite (relative or absolute).")
    content: str = Field(..., description="The complete file content to write.")


class FileWriteTool(BaseTool):
    """Tool for writing content to files in the local workspace."""

    name: str = "file_write_tool"
    description: str = (
        "Writes content to a file in the repository workspace. "
        "Provide file_path (relative like 'src/main.py' or absolute) and full content. "
        "Parent directories are created automatically. Overwrites if file exists. "
        "Dotfiles like .eslintrc.json are handled correctly."
    )
    args_schema: Type[BaseModel] = FileWriteInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _run(self, file_path: str, content: str) -> str:
        """Write content to a file in the workspace."""
        try:
            # Content size guard
            if len(content) > MAX_FILE_WRITE_BYTES:
                return json.dumps({
                    "success": False,
                    "error": f"Content too large ({len(content)} chars). Max: {MAX_FILE_WRITE_BYTES}"
                })

            # Normalize path
            full_path = normalize_workspace_path(file_path, self.workspace_dir)

            # Security check
            if not validate_path_in_workspace(full_path, self.workspace_dir):
                return json.dumps({
                    "success": False,
                    "error": f"Path '{file_path}' resolves outside the workspace. "
                             f"Use a relative path like 'src/test.py'."
                })

            # Create parent directories
            parent_dir = os.path.dirname(full_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Write the file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            size = os.path.getsize(full_path)
            rel_path = os.path.relpath(full_path, self.workspace_dir)
            return json.dumps({
                "success": True,
                "message": f"Successfully wrote {size} bytes to '{rel_path}'",
                "absolute_path": full_path
            })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to write file '{file_path}': {str(e)}"
            })
