"""
Multi-language test coverage tool.
Auto-detects project languages and runs appropriate test frameworks with coverage.
All per-language logic lives in _language_detector.py.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any
import subprocess
import os
import json
import logging

from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, COVERAGE_DIR, MAX_TEST_OUTPUT_CHARS
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages, detect_test_framework, build_project_profile,
    TEST_FRAMEWORK_DETECTION
)

logger = logging.getLogger(__name__)


class TestCoverageInput(BaseModel):
    """Input schema for Test Coverage Tool."""
    target_path: Optional[str] = Field(
        default=None,
        description=(
            "Project directory to run tests in. "
            "If a directory, it becomes the working directory. "
            "Defaults to the workspace root."
        )
    )
    with_coverage: bool = Field(
        default=True,
        description="Run with coverage reporting. Set to false for plain test run."
    )


class TestCoverageTool(BaseTool):
    """Multi-language test runner with coverage — auto-detects frameworks."""

    name: str = "test_coverage_tool"
    description: str = (
        "Runs tests with coverage tracking. AUTO-DETECTS the project language(s) "
        "and runs the appropriate test framework (pytest for Python, jest/vitest for JS, "
        "mvn test for Java, ctest for C/C++, cargo test for Rust, go test for Go, etc.). "
        "Provide target_path as the project directory for best results. "
        "Returns structured results per language with coverage percentages."
    )
    args_schema: Type[BaseModel] = TestCoverageInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

    def _truncate(self, text: str) -> str:
        if len(text) <= MAX_TEST_OUTPUT_CHARS:
            return text
        half = MAX_TEST_OUTPUT_CHARS // 2
        return (
            text[:half]
            + f"\n... [TRUNCATED: {len(text)} chars] ...\n"
            + text[-half:]
        )

    def _resolve_cwd(self, target_path: Optional[str]) -> str:
        """Resolve working directory from target_path."""
        if target_path:
            abs_target = os.path.abspath(target_path)
            if os.path.isdir(abs_target):
                return abs_target
            combined = os.path.abspath(os.path.join(self.workspace_dir, target_path))
            if os.path.isdir(combined):
                return combined
            logger.warning(f"target_path '{target_path}' not found, using workspace")
        return os.path.abspath(self.workspace_dir)

    def _exec(self, cmd: str, cwd: str, timeout: int = 300) -> Dict[str, Any]:
        """Run a shell command."""
        try:
            env = os.environ.copy()
            env["CI"] = "true"
            env["PYTHONUNBUFFERED"] = "1"
            env["FORCE_COLOR"] = "0"
            env["NO_COLOR"] = "1"

            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout, env=env
            )
            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": self._truncate(result.stdout),
                "stderr": self._truncate(result.stderr),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False, "exit_code": -1,
                "stdout": "", "stderr": f"Tests timed out after {timeout}s"
            }
        except Exception as e:
            return {
                "success": False, "exit_code": -1,
                "stdout": "", "stderr": f"{type(e).__name__}: {e}"
            }

    # ── Coverage Parsers (generic dispatch) ───────────────

    def _parse_coverage(self, lang: str, cwd: str) -> Dict[str, Any]:
        """Dispatch to language-specific coverage parser."""
        parsers = {
            "python": self._parse_python_coverage,
            "javascript": self._parse_js_coverage,
            "typescript": self._parse_js_coverage,
            "go": self._parse_go_coverage,
        }
        parser = parsers.get(lang)
        if parser:
            return parser(cwd)
        return {"percent": None, "source": None}

    def _parse_python_coverage(self, cwd: str) -> Dict[str, Any]:
        """Parse Python coverage JSON output."""
        search_paths = [
            os.path.join(cwd, ".coverage_data", "coverage.json"),
            os.path.join(COVERAGE_DIR, "coverage.json"),
            os.path.join(cwd, "coverage.json"),
            os.path.join(cwd, "htmlcov", "status.json"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    pct = data.get("totals", {}).get("percent_covered", 0)
                    return {"percent": round(pct, 2), "source": path}
                except Exception:
                    pass
        return {"percent": None, "source": None}

    def _parse_js_coverage(self, cwd: str) -> Dict[str, Any]:
        """Parse Jest/Vitest coverage JSON summary."""
        search_paths = [
            os.path.join(cwd, "coverage", "coverage-summary.json"),
            os.path.join(cwd, "coverage", "coverage-final.json"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Jest summary format
                    total = data.get("total", {})
                    lines = total.get("lines", {}).get("pct")
                    if lines is not None:
                        return {"percent": round(lines, 2), "source": path}
                    # coverage-final format: compute from file data
                    if "total" not in data and len(data) > 0:
                        total_stmts = 0
                        covered_stmts = 0
                        for file_data in data.values():
                            s = file_data.get("s", {})
                            total_stmts += len(s)
                            covered_stmts += sum(1 for v in s.values() if v > 0)
                        if total_stmts > 0:
                            pct = (covered_stmts / total_stmts) * 100
                            return {"percent": round(pct, 2), "source": path}
                except Exception:
                    pass
        return {"percent": None, "source": None}

    def _parse_go_coverage(self, cwd: str) -> Dict[str, Any]:
        """Parse Go coverage profile."""
        cov_path = os.path.join(cwd, "coverage.out")
        if os.path.exists(cov_path):
            try:
                result = subprocess.run(
                    f"go tool cover -func={cov_path}",
                    shell=True, cwd=cwd,
                    capture_output=True, text=True, timeout=30
                )
                # Last line: "total: (statements)  XX.X%"
                for line in reversed(result.stdout.strip().split("\n")):
                    if "total:" in line:
                        pct_str = line.split()[-1].rstrip("%")
                        return {"percent": round(float(pct_str), 2), "source": cov_path}
            except Exception:
                pass
        return {"percent": None, "source": None}

    # ── Main entry ────────────────────────────────────────

    def _run(self, target_path: str = None, with_coverage: bool = True) -> str:
        cwd = self._resolve_cwd(target_path)

        if not os.path.exists(cwd):
            return json.dumps({"success": False, "error": f"Directory '{cwd}' not found."})

        os.makedirs(COVERAGE_DIR, exist_ok=True)

        languages = detect_languages(cwd)
        report = {
            "success": True,
            "working_directory": cwd,
            "languages_detected": languages,
            "results_per_language": {},
            "errors": [],
        }

        if not languages:
            report["success"] = False
            report["errors"].append(f"No recognized languages in '{cwd}'.")
            return json.dumps(report, indent=2)

        for lang in languages:
            lang_config = TEST_FRAMEWORK_DETECTION.get(lang, {})
            fw_name = detect_test_framework(cwd, lang)

            if not fw_name or fw_name not in lang_config.get("frameworks", {}):
                report["results_per_language"][lang] = {
                    "skipped": True,
                    "reason": f"No test framework detected for {lang}",
                }
                continue

            fw = lang_config["frameworks"][fw_name]
            cmd = fw.get("coverage_cmd") if with_coverage else fw.get("test_cmd")
            if not cmd:
                cmd = fw.get("test_cmd", "")

            if not cmd:
                report["results_per_language"][lang] = {
                    "skipped": True,
                    "reason": f"No test command defined for {lang}/{fw_name}",
                }
                continue

            # For Python, redirect coverage output
            if lang == "python" and with_coverage and "--cov-report=json" in cmd:
                cov_json = os.path.join(cwd, ".coverage_data", "coverage.json")
                os.makedirs(os.path.dirname(cov_json), exist_ok=True)
                cmd = cmd.replace("--cov-report=json", f"--cov-report=json:{cov_json}")

            logger.info(f"Running tests for {lang}/{fw_name}: {cmd}")
            result = self._exec(cmd, cwd)

            # Parse coverage
            coverage = self._parse_coverage(lang, cwd)

            entry = {
                "framework": fw_name,
                "command": cmd,
                "tests_passed": result["success"],
                "exit_code": result["exit_code"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "coverage_percent": coverage.get("percent"),
                "coverage_source": coverage.get("source"),
                "coverage_meets_threshold": (
                    coverage["percent"] >= 70.0
                    if coverage["percent"] is not None
                    else None
                ),
            }

            report["results_per_language"][lang] = entry

            if not result["success"]:
                report["success"] = False

        return json.dumps(report, indent=2)