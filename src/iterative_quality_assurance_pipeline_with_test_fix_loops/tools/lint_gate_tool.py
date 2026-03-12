"""
Multi-language lint gate tool.

ONLY runs linters. Does NOT install dependencies or create configs.
Use dependency_installer_tool first to ensure everything is ready.

All per-language logic lives in _language_detector.TEST_FRAMEWORK_DETECTION.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any
import subprocess
import os
import json
import logging

from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_LINT_OUTPUT_CHARS
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages, TEST_FRAMEWORK_DETECTION
)

logger = logging.getLogger(__name__)


class LintGateInput(BaseModel):
    """Input schema for Lint Gate Tool."""
    target_path: Optional[str] = Field(
        default=None,
        description=(
            "Optional: specific file or directory to lint. "
            "If a directory, it becomes the working directory. "
            "Defaults to the entire workspace."
        )
    )


class LintGateTool(BaseTool):
    """Multi-language lint gate — runs linters detected from project data."""

    name: str = "lint_gate_tool"
    description: str = (
        "Runs static analysis linters on the repository. AUTO-DETECTS the project "
        "language(s) and runs appropriate linters. "
        "IMPORTANT: Call dependency_installer_tool first to ensure linters are installed. "
        "Provide target_path as the project directory for best results."
    )
    args_schema: Type[BaseModel] = LintGateInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

    def _truncate(self, text: str) -> str:
        if len(text) <= MAX_LINT_OUTPUT_CHARS:
            return text
        return text[:MAX_LINT_OUTPUT_CHARS] + f"\n... [TRUNCATED: {len(text)} total chars]"

    def _resolve_cwd_and_target(self, target_path: Optional[str]) -> tuple:
        """Resolve working directory and lint target."""
        if target_path:
            abs_target = os.path.abspath(target_path)
            if os.path.isdir(abs_target):
                return abs_target, "."
            if os.path.isfile(abs_target):
                return os.path.dirname(abs_target), os.path.basename(abs_target)
            combined = os.path.abspath(os.path.join(self.workspace_dir, target_path))
            if os.path.isdir(combined):
                return combined, "."
            if os.path.isfile(combined):
                return os.path.dirname(combined), os.path.basename(combined)
            logger.warning(f"target_path '{target_path}' not found, falling back to workspace")
        return os.path.abspath(self.workspace_dir), "."

    def _run_linter(self, cmd: str, cwd: str, timeout: int = 120) -> Dict[str, Any]:
        """Run a single linter command."""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1"},
            )
            output = (result.stdout + result.stderr).strip()
            return {
                "passed": result.returncode == 0,
                "output": self._truncate(output) if output else "No output (clean)",
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": f"Timed out after {timeout}s", "exit_code": -1}
        except Exception as e:
            return {"passed": False, "output": f"{type(e).__name__}: {e}", "exit_code": -1}

    def _run(self, target_path: str = None) -> str:
        cwd, target = self._resolve_cwd_and_target(target_path)

        if not os.path.exists(cwd):
            return json.dumps({"success": False, "error": f"Directory '{cwd}' not found."})

        logger.info(f"LintGateTool: cwd={cwd}, target={target}")
        languages = detect_languages(cwd)

        report = {
            "success": True,
            "working_directory": cwd,
            "target": target,
            "languages_detected": languages,
            "linter_results": {},
            "summary": {"total": 0, "passed": 0, "failed": 0},
            "errors": [],
        }

        if not languages:
            report["errors"].append(f"No recognized languages in '{cwd}'.")
            return json.dumps(report, indent=2)

        for lang in languages:
            lang_config = TEST_FRAMEWORK_DETECTION.get(lang, {})
            linters = lang_config.get("linters", {})

            for linter_name, linter_info in linters.items():
                cmd = linter_info["cmd"]
                if target != ".":
                    cmd = cmd.replace(" .", f" {target}")

                report["summary"]["total"] += 1
                result = self._run_linter(cmd, cwd)
                key = f"{lang}/{linter_name}"
                report["linter_results"][key] = result

                if result["passed"]:
                    report["summary"]["passed"] += 1
                else:
                    report["summary"]["failed"] += 1
                    report["success"] = False

        s = report["summary"]
        report["summary_text"] = (
            f"{s['total']} linters run: {s['passed']} passed, {s['failed']} failed"
        )
        return json.dumps(report, indent=2)