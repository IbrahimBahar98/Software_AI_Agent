"""
CI/CD config reader tool for the QA pipeline.
Reads GitHub Actions, GitLab CI, Jenkins, etc.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional
import os
import json
import glob
import logging
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


class CIConfigReaderInput(BaseModel):
    """Input schema for CI Config Reader Tool."""
    target_path: Optional[str] = Field(
        default=None,
        description=(
            "Optional: project directory to scan for CI configs. "
            "Defaults to the workspace root."
        )
    )


class CIConfigReaderTool(BaseTool):
    """Tool for reading CI/CD workflow configurations from the repository."""

    name: str = "ci_config_reader_tool"
    description: str = (
        "Reads CI/CD configuration files from the repository. "
        "Supports GitHub Actions (.github/workflows/*.yml), GitLab CI (.gitlab-ci.yml), "
        "Jenkins (Jenkinsfile), CircleCI, Travis CI, Azure Pipelines, and more. "
        "Returns a summarized JSON report. Provide target_path for a specific project."
    )
    args_schema: Type[BaseModel] = CIConfigReaderInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

    def _resolve_cwd(self, target_path: Optional[str]) -> str:
        if target_path:
            abs_target = os.path.abspath(target_path)
            if os.path.isdir(abs_target):
                return abs_target
            combined = os.path.abspath(os.path.join(self.workspace_dir, target_path))
            if os.path.isdir(combined):
                return combined
        return os.path.abspath(self.workspace_dir)

    def _summarize_workflow(self, workflow: dict) -> dict:
        """Extract key information from a parsed GitHub Actions workflow."""
        if not isinstance(workflow, dict):
            return {"error": "Invalid workflow structure"}

        summary = {
            "name": workflow.get("name", "unnamed"),
            "triggers": [],
            "jobs": {}
        }

        on_config = workflow.get("on", {})
        if isinstance(on_config, dict):
            summary["triggers"] = list(on_config.keys())
        elif isinstance(on_config, list):
            summary["triggers"] = on_config
        else:
            summary["triggers"] = [str(on_config)]

        for job_name, job_config in workflow.get("jobs", {}).items():
            if not isinstance(job_config, dict):
                continue
            steps = job_config.get("steps", [])
            commands = []
            actions_used = []
            for step in steps:
                if isinstance(step, dict):
                    if "run" in step:
                        commands.append(str(step["run"])[:200])
                    if "uses" in step:
                        actions_used.append(step["uses"])

            summary["jobs"][job_name] = {
                "runs_on": job_config.get("runs-on", "unknown"),
                "num_steps": len(steps),
                "actions_used": actions_used,
                "run_commands": commands[:10],
            }

        return summary

    def _run(self, target_path: str = None) -> str:
        if yaml is None:
            return json.dumps({
                "success": False,
                "error": "PyYAML not installed. Run: pip install pyyaml"
            })

        cwd = self._resolve_cwd(target_path)
        results = {"github_actions": {}, "other_ci": []}

        # GitHub Actions
        workflows_dir = os.path.join(cwd, ".github", "workflows")
        if os.path.exists(workflows_dir):
            yml_files = (
                glob.glob(os.path.join(workflows_dir, "*.yml"))
                + glob.glob(os.path.join(workflows_dir, "*.yaml"))
            )
            for file_path in yml_files:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        workflow = yaml.safe_load(f)
                    filename = os.path.basename(file_path)
                    results["github_actions"][filename] = self._summarize_workflow(workflow)
                except Exception as e:
                    results["github_actions"][os.path.basename(file_path)] = {
                        "error": str(e)
                    }

        # Other CI systems
        ci_files = {
            ".gitlab-ci.yml": "GitLab CI",
            "Jenkinsfile": "Jenkins",
            ".circleci/config.yml": "CircleCI",
            ".travis.yml": "Travis CI",
            "azure-pipelines.yml": "Azure Pipelines",
            "bitbucket-pipelines.yml": "Bitbucket Pipelines",
            ".drone.yml": "Drone CI",
            "Makefile": "Make (build system)",
        }
        for ci_file, ci_name in ci_files.items():
            ci_path = os.path.join(cwd, ci_file)
            if os.path.exists(ci_path):
                results["other_ci"].append({
                    "system": ci_name,
                    "file": ci_file,
                    "exists": True,
                })

        has_any = bool(results["github_actions"]) or bool(results["other_ci"])
        return json.dumps({
            "success": True,
            "working_directory": cwd,
            "ci_found": has_any,
            "workflows": results,
        }, indent=2)