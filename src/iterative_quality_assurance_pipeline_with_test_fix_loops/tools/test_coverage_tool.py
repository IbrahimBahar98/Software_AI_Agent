from crewai.tools import BaseTool
from pydantic import BaseModel
from typing import Type
import subprocess
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, COVERAGE_DIR, MAX_TEST_OUTPUT_CHARS
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages, build_project_profile
)


class TestCoverageInput(BaseModel):
    """Input schema for Test Coverage Tool."""
    pass


class TestCoverageTool(BaseTool):
    """Multi-language test runner with coverage — auto-detects frameworks."""

    name: str = "test_coverage_tool"
    description: str = (
        "Runs tests with coverage tracking. AUTO-DETECTS the project language(s) "
        "and runs the appropriate test framework (pytest for Python, jest/vitest for JS, "
        "mvn test for Java, ctest for C/C++, cargo test for Rust, go test for Go, etc.). "
        "Returns structured results per language."
    )
    args_schema: Type[BaseModel] = TestCoverageInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _truncate(self, text: str) -> str:
        if len(text) <= MAX_TEST_OUTPUT_CHARS:
            return text
        half = MAX_TEST_OUTPUT_CHARS // 2
        return (
            text[:half] +
            f"\n... [TRUNCATED: {len(text)} chars] ...\n" +
            text[-half:]
        )

    def _run_test_command(self, cmd: str, cwd: str, timeout: int = 300) -> dict:
        """Run a test command and return structured result."""
        try:
            env = os.environ.copy()
            env["CI"] = "true"
            env["PYTHONUNBUFFERED"] = "1"

            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout, env=env
            )
            return {
                "tests_passed": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": self._truncate(result.stdout),
                "stderr": self._truncate(result.stderr),
            }
        except subprocess.TimeoutExpired:
            return {
                "tests_passed": False, "exit_code": -1,
                "stdout": "", "stderr": f"Tests timed out after {timeout}s"
            }
        except FileNotFoundError:
            return {
                "tests_passed": False, "exit_code": -1,
                "stdout": "", "stderr": "Test command not found"
            }
        except Exception as e:
            return {
                "tests_passed": False, "exit_code": -1,
                "stdout": "", "stderr": str(e)
            }

    def _parse_python_coverage(self, cwd: str) -> dict:
        """Try to parse Python coverage JSON output."""
        for path in [
            os.path.join(COVERAGE_DIR, "coverage.json"),
            os.path.join(cwd, "coverage.json"),
        ]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    return {
                        "percent": round(data.get("totals", {}).get("percent_covered", 0), 2),
                        "source": path
                    }
                except Exception:
                    pass
        return {"percent": None, "source": None}

    def _parse_jest_coverage(self, cwd: str) -> dict:
        """Try to parse Jest coverage JSON summary."""
        summary_path = os.path.join(cwd, "coverage", "coverage-summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r") as f:
                    data = json.load(f)
                total = data.get("total", {})
                lines = total.get("lines", {}).get("pct", 0)
                return {"percent": round(lines, 2), "source": summary_path}
            except Exception:
                pass
        return {"percent": None, "source": None}

    def _run(self) -> str:
        cwd = os.path.abspath(self.workspace_dir)
        if not os.path.exists(cwd):
            return json.dumps({"success": False, "error": f"Workspace '{cwd}' not found."})

        os.makedirs(COVERAGE_DIR, exist_ok=True)
        profile = build_project_profile(cwd)

        report = {
            "success": True,
            "languages_detected": profile.languages,
            "results_per_language": {},
        }

        if not profile.languages:
            report["success"] = False
            report["error"] = "No recognized languages detected."
            return json.dumps(report, indent=2)

        any_failed = False

        for lang in profile.languages:
            coverage_cmd = profile.coverage_commands.get(lang)
            test_cmd = profile.test_commands.get(lang)
            cmd = coverage_cmd or test_cmd

            if not cmd:
                report["results_per_language"][lang] = {
                    "skipped": True,
                    "reason": "No test command detected for this language."
                }
                continue

            # For Python, redirect coverage output to COVERAGE_DIR
            if lang == "python" and coverage_cmd:
                cov_json = os.path.join(COVERAGE_DIR, "coverage.json")
                cmd = cmd.replace("--cov-report=json", f"--cov-report=json:{cov_json}")

            result = self._run_test_command(cmd, cwd)

            # Try to parse coverage data
            coverage = {"percent": None}
            if lang == "python":
                coverage = self._parse_python_coverage(cwd)
            elif lang in ("javascript", "typescript"):
                coverage = self._parse_jest_coverage(cwd)

            result["coverage_percent"] = coverage.get("percent")
            result["coverage_meets_threshold"] = (
                coverage["percent"] >= 70.0 if coverage["percent"] is not None else None
            )
            result["command_used"] = cmd

            report["results_per_language"][lang] = result

            if not result["tests_passed"]:
                any_failed = True

        report["success"] = not any_failed
        return json.dumps(report, indent=2)