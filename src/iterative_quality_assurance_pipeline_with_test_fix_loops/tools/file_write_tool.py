from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import os
import json


from iterative_quality_assurance_pipeline_with_test_fix_loops.config import WORKSPACE_DIR, REPO_DIR

class FileWriteInput(BaseModel):
    """Input schema for File Write Tool."""
    file_path: str = Field(..., description="Relative path within the workspace to create/overwrite the file (e.g., 'src/utils.py').")
    content: str = Field(..., description="The complete file content to write.")

class FileWriteTool(BaseTool):
    """Tool for writing content to files in the local workspace.
    
    Safer and more reliable than piping through bash echo commands.
    Automatically creates parent directories if they don't exist.
    """

    name: str = "file_write_tool"
    description: str = (
        "Writes content to a file in the local workspace directory. "
        "Provide a relative file_path (e.g., 'src/main.py') and the full content to write. "
        "Parent directories are created automatically. Overwrites if file exists."
    )
    args_schema: Type[BaseModel] = FileWriteInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _run(self, file_path: str, content: str) -> str:
        """Write content to a file in the workspace."""
        try:
            # Clean up file_path to prevent duplication if agent prepends workspace or repo dir
            # e.g., if file_path is './workspace/repo/src/test.py', change to 'src/test.py'
            clean_path = file_path.replace("\\", "/").strip("./ ")
            prefixes_to_strip = ["workspace/", "repo/", "./workspace/", "./repo/"]
            for prefix in prefixes_to_strip:
                if clean_path.startswith(prefix):
                    clean_path = clean_path[len(prefix):]
                if clean_path.startswith("repo/"):
                    clean_path = clean_path[len("repo/"):]
            clean_path = clean_path.strip("/")
            
            # Resolve full path
            full_path = os.path.join(self.workspace_dir, clean_path)
            full_path = os.path.normpath(full_path)

            # Security: ensure we stay within workspace
            abs_workspace = os.path.abspath(self.workspace_dir)
            abs_target = os.path.abspath(full_path)
            if not abs_target.startswith(abs_workspace):
                return json.dumps({
                    "success": False, 
                    "error": f"Path '{file_path}' escapes the workspace directory."
                })

            # Create parent directories
            parent_dir = os.path.dirname(full_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Write the file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            size = os.path.getsize(full_path)
            return json.dumps({
                "success": True, 
                "message": f"Successfully wrote {size} bytes to '{file_path}'"
            })

        except Exception as e:
            return json.dumps({
                "success": False, 
                "error": f"Failed to write file '{file_path}': {str(e)}"
            })
