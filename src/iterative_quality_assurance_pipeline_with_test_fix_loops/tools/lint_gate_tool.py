from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional
import subprocess
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_LINT_OUTPUT_CHARS
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages, build_project_profile, TEST_FRAMEWORK_DETECTION
)


class LintGateInput(BaseModel):
    """Input schema for Lint Gate Tool."""
    target_path: Optional[str] = Field(
        default=None,
        description="Optional: specific file or directory to lint. Defaults to entire workspace."
    )


class LintGateTool(BaseTool):
    """Multi-language lint gate — auto-detects project languages and runs appropriate linters."""

    name: str = "lint_gate_tool"
    description: str = (
        "Runs static analysis on the repository. AUTO-DETECTS the project language(s) "
        "and runs appropriate linters (ruff/mypy for Python, eslint for JS/TS, "
        "checkstyle for Java, cppcheck for C/C++, clippy for Rust, go vet for Go, etc.). "
        "Optionally provide target_path to lint a specific file or directory."
    )
    args_schema: Type[BaseModel] = LintGateInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _truncate(self, text: str) -> str:
        if len(text) <= MAX_LINT_OUTPUT_CHARS:
            return text
        return text[:MAX_LINT_OUTPUT_CHARS] + f"\n... [TRUNCATED: {len(text)} total chars]"

    def _run_linter(self, cmd: str, cwd: str, timeout: int = 120) -> dict:
        """Run a single linter command and return structured result."""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout
            )
            output = (result.stdout + result.stderr).strip()
            return {
                "passed": result.returncode == 0,
                "output": self._truncate(output) if output else "No output",
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": f"Timed out after {timeout}s", "exit_code": -1}
        except FileNotFoundError:
            return {"passed": False, "output": "Command not found", "exit_code": -1}
        except Exception as e:
            return {"passed": False, "output": str(e), "exit_code": -1}

    def _run(self, target_path: str = None) -> str:
        cwd = os.path.abspath(self.workspace_dir)
        if not os.path.exists(cwd):
            return json.dumps({"success": False, "error": f"Workspace '{cwd}' not found."})

        target = target_path or "."
        languages = detect_languages(cwd)

        report = {
            "success": True,
            "languages_detected": languages,
            "linter_results": {},
            "errors": []
        }

        if not languages:
            report["errors"].append("No recognized programming languages detected.")
            return json.dumps(report, indent=2)

        for lang in languages:
            lang_config = TEST_FRAMEWORK_DETECTION.get(lang, {})
            linters = lang_config.get("linters", {})

            for linter_name, linter_info in linters.items():
                cmd = linter_info["cmd"]
                # Replace '.' with target if specified
                if target != ".":
                    cmd = cmd.replace(" .", f" {target}")

                result = self._run_linter(cmd, cwd)
                key = f"{lang}/{linter_name}"
                report["linter_results"][key] = result

                if not result["passed"]:
                    report["success"] = False

        return json.dumps(report, indent=2)