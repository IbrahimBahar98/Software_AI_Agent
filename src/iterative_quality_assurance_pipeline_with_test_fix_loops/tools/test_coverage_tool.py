from crewai.tools import BaseTool
from pydantic import BaseModel
from typing import Type
import subprocess
import os
import json

class TestCoverageInput(BaseModel):
    """Input schema for Test Coverage Tool."""
    pass # No input required

class TestCoverageTool(BaseTool):
    """Tool for running pytest with coverage analysis against the workspace."""

    name: str = "test_coverage_tool"
    description: str = (
        "Runs pytest with coverage tracking enabled. Fails if coverage is under 70%. "
        "Returns a detailed JSON string containing overall coverage percentage, "
        "pass/fail status, and coverage metrics per file."
    )
    args_schema: Type[BaseModel] = TestCoverageInput
    workspace_dir: str = "./workspace"

    def __init__(self, workspace_dir: str = "./workspace", **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = workspace_dir

    def _run(self) -> str:
        """Execute pytest --cov on the workspace."""
        try:
            cwd = os.path.abspath(self.workspace_dir)
            if not os.path.exists(cwd):
                return json.dumps({"success": False, "error": f"Workspace directory '{cwd}' not found."})

            # Run pytest with pytest-cov
            # Using --cov-report=json to parse the results, and text to show it
            cmd = ["pytest", "--cov=.", "--cov-report=json", "--cov-fail-under=70"]
            
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True
            )
            
            coverage_json_path = os.path.join(cwd, "coverage.json")
            coverage_data = {}
            if os.path.exists(coverage_json_path):
                try:
                    with open(coverage_json_path, "r", encoding="utf-8") as f:
                        coverage_data = json.load(f)
                except Exception:
                    pass
                
            overall_cov = coverage_data.get("totals", {}).get("percent_covered", 0.0)

            report = {
                "success": result.returncode == 0,
                "coverage_percent": round(overall_cov, 2),
                "terminal_output": result.stdout,
                "terminal_error": result.stderr,
                "coverage_json_generated": bool(coverage_data)
            }
            
            return json.dumps(report)

        except FileNotFoundError:
             return json.dumps({"success": False, "error": "pytest or pytest-cov is not installed. Ensure they are in PATH."})
        except Exception as e:
            return json.dumps({"success": False, "error": f"Coverage execution failed: {str(e)}"})
