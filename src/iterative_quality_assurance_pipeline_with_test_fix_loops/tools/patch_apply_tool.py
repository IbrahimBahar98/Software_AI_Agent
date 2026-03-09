from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess
import os
import tempfile
import json

class PatchApplyInput(BaseModel):
    """Input schema for Patch Apply Tool."""
    file_path: str = Field(..., description="Relative path within the workspace to the file to patch (e.g., 'src/main.py').")
    patch_content: str = Field(..., description="The unified diff / patch content to apply.")

class PatchApplyTool(BaseTool):
    """Tool for applying unified diff patches to local workspace files.
    
    This replaces full-file overwrites for the fixing agent, reducing 
    token usage and preventing destructive overwrites of large files.
    """

    name: str = "patch_apply_tool"
    description: str = (
        "Applies a unified diff patch to a file. Provide the relative 'file_path' "
        "and the 'patch_content' (the diff). This is safer than overwriting entire files."
    )
    args_schema: Type[BaseModel] = PatchApplyInput
    workspace_dir: str = "./workspace"

    def __init__(self, workspace_dir: str = "./workspace", **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = workspace_dir

    def _run(self, file_path: str, patch_content: str) -> str:
        """Apply a patch to a file in the workspace."""
        try:
            full_path = os.path.join(self.workspace_dir, file_path)
            full_path = os.path.normpath(full_path)
            
            # Security: ensure we stay within workspace
            abs_workspace = os.path.abspath(self.workspace_dir)
            abs_target = os.path.abspath(full_path)
            if not abs_target.startswith(abs_workspace):
                return json.dumps({
                    "success": False, 
                    "error": f"Path '{file_path}' escapes the workspace directory."
                })
                
            if not os.path.exists(full_path):
                return json.dumps({
                    "success": False,
                    "error": f"File '{file_path}' does not exist. Cannot patch."
                })

            # Create a temporary file for the patch content
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.patch', encoding='utf-8') as temp_patch:
                # Ensure the patch uses the correct line endings format, patch is sensitive to this
                # Sometimes LLMs don't format diffs perfectly. We'll dump what they gave us.
                temp_patch.write(patch_content)
                temp_patch_path = temp_patch.name

            try:
                # Try to apply the patch using git apply or standard patch
                # 'patch' tool is usually available on Linux/macOS and in Git Bash on Windows
                result = subprocess.run(
                    ["patch", "-p1", full_path],
                    input=patch_content,
                    text=True,
                    capture_output=True,
                    cwd=self.workspace_dir
                )
                
                if result.returncode == 0:
                    return json.dumps({
                        "success": True,
                        "message": f"Successfully applied patch to '{file_path}'",
                        "log": result.stdout
                    })
                
                # Fallback: try git apply if patch fails (requires the file to be in a git repo)
                result_git = subprocess.run(
                    ["git", "apply", "--ignore-whitespace", temp_patch_path],
                    capture_output=True,
                    text=True,
                    cwd=self.workspace_dir
                )
                if result_git.returncode == 0:
                    return json.dumps({
                        "success": True,
                        "message": f"Successfully applied git patch to '{file_path}'",
                        "log": result_git.stdout
                    })
                    
                return json.dumps({
                    "success": False,
                    "error": "Failed to apply patch.",
                    "patch_output": result.stderr + result.stdout,
                    "git_apply_output": result_git.stderr + result_git.stdout
                })
                
            finally:
                if os.path.exists(temp_patch_path):
                    os.unlink(temp_patch_path)

        except Exception as e:
            return json.dumps({
                "success": False, 
                "error": f"Failed to patch file '{file_path}': {str(e)}"
            })
