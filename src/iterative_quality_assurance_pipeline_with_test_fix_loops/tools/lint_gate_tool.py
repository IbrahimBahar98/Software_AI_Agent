from crewai.tools import BaseTool
from pydantic import BaseModel
from typing import Type
import subprocess
import os
import json

class LintGateInput(BaseModel):
    """Input schema for Lint Gate Tool."""
    pass # No input required, runs on the entire workspace

class LintGateTool(BaseTool):
    """Tool for running fast static analysis (ruff and mypy) against the workspace.
    
    Acts as a pre-check to catch syntax errors, missing imports, and type mismatches
    before running the full pytest suite. This saves tokens by preventing the test 
    execution agent from crashing on fundamental errors.
    """

    name: str = "lint_gate_tool"
    description: str = (
        "Runs static analysis (ruff and mypy) on the local workspace directory. "
        "Returns a structured JSON report. Call this before running tests to ensure "
        "the code is syntactically sound."
    )
    args_schema: Type[BaseModel] = LintGateInput
    workspace_dir: str = "./workspace"

    def __init__(self, workspace_dir: str = "./workspace", **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = workspace_dir

    def _run(self) -> str:
        """Execute ruff and mypy on the workspace."""
        if not os.path.exists(self.workspace_dir):
            return json.dumps({
                "success": False,
                "error": f"Workspace directory '{self.workspace_dir}' does not exist."
            })
            
        cwd = os.path.abspath(self.workspace_dir)
        report = {
            "success": True,
            "ruff_passed": True,
            "mypy_passed": True,
            "errors": []
        }

        # 1. Run ruff (fast linter and syntax checker)
        try:
            ruff_result = subprocess.run(
                ["ruff", "check", "."],
                cwd=cwd,
                capture_output=True,
                text=True
            )
            if ruff_result.returncode != 0:
                report["success"] = False
                report["ruff_passed"] = False
                report["errors"].append({
                    "tool": "ruff",
                    "output": ruff_result.stdout + ruff_result.stderr
                })
        except FileNotFoundError:
             report["errors"].append({"tool": "ruff", "error": "ruff is not installed or not in PATH."})
             report["success"] = False
             report["ruff_passed"] = False

        # 2. Run mypy (type checker)
        try:
            mypy_result = subprocess.run(
                ["mypy", "."],
                cwd=cwd,
                capture_output=True,
                text=True
            )
            if mypy_result.returncode != 0:
                report["success"] = False
                report["mypy_passed"] = False
                report["errors"].append({
                    "tool": "mypy",
                    "output": mypy_result.stdout + mypy_result.stderr
                })
        except FileNotFoundError:
             report["errors"].append({"tool": "mypy", "error": "mypy is not installed or not in PATH."})
             report["success"] = False
             report["mypy_passed"] = False

        return json.dumps(report)
