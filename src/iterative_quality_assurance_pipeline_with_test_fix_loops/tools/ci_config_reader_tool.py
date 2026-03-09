from crewai.tools import BaseTool
from pydantic import BaseModel
from typing import Type
import yaml
import os
import json
import glob

class CIConfigReaderInput(BaseModel):
    """Input schema for CI Config Reader Tool."""
    pass

class CIConfigReaderTool(BaseTool):
    """Tool for reading existing GitHub Actions workflow configurations."""

    name: str = "ci_config_reader_tool"
    description: str = (
        "Reads existing `.github/workflows/*.yml` files in the repository. "
        "Returns a JSON summary of the CI environment, including Python versions, "
        "test commands, linters, and environment variables used by the upstream project."
    )
    args_schema: Type[BaseModel] = CIConfigReaderInput
    workspace_dir: str = "./workspace"

    def __init__(self, workspace_dir: str = "./workspace", **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = workspace_dir

    def _run(self) -> str:
        """Parse CI configuration files using PyYAML."""
        workflows_dir = os.path.join(self.workspace_dir, ".github", "workflows")
        
        if not os.path.exists(workflows_dir):
            return json.dumps({"success": False, "message": "No .github/workflows directory found."})
            
        yml_files = glob.glob(os.path.join(workflows_dir, "*.yml")) + glob.glob(os.path.join(workflows_dir, "*.yaml"))
        
        if not yml_files:
            return json.dumps({"success": False, "message": "No YAML workflow files found."})

        results = {}
        for file_path in yml_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    workflow = yaml.safe_load(f)
                    
                filename = os.path.basename(file_path)
                results[filename] = workflow
            except yaml.YAMLError as exc:
                results[os.path.basename(file_path)] = {"parse_error": str(exc)}
            except Exception as e:
                results[os.path.basename(file_path)] = {"error": str(e)}

        return json.dumps({"success": True, "workflows": results}, indent=2)
