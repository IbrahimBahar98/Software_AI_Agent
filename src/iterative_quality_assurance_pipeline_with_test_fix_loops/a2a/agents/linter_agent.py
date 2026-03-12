"""
Linter Agent — Runs static analysis on any detected language.

Zero hardcoded linter knowledge. Receives available tools from
the discovery agent's PATH scan and runs whatever is available.
The LLM agents decide WHICH linters to ask for — this agent
just executes them and returns structured results.
"""

import os
import json
import subprocess
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator

from ..models import (
    AgentCard, AgentSkill, Task, TaskState, TaskStatus,
    Message, Artifact,
)

logger = logging.getLogger(__name__)


class LinterAgent:
    """
    Executes linter commands and returns structured results.

    Philosophy:
    - Does NOT decide which linters to run (that's the LLM's job)
    - Does NOT know linter-specific output formats
    - DOES execute commands safely and parse exit codes
    - DOES extract error lines/files from output heuristically
    - DOES handle timeouts and failures gracefully

    The calling agent sends:
    {
        "repo_dir": "/path/to/repo",
        "commands": {
            "python/ruff": "ruff check .",
            "javascript/eslint": "npx eslint . --ext .js,.jsx",
            "cpp/cppcheck": "cppcheck --enable=all --quiet ."
        }
    }

    Or for auto-detection (if discovery data is passed):
    {
        "repo_dir": "/path/to/repo",
        "available_tools": {"ruff": "0.3.0", "eslint": "8.0.0"},
        "languages": {"python": 42, "javascript": 15},
        "auto_detect": true
    }
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    def _exec(
        self, cmd: str, cwd: str, timeout: int = 120
    ) -> Dict[str, Any]:
        """Execute a command and return structured result."""
        try:
            env = os.environ.copy()
            env.update({
                "FORCE_COLOR": "0",
                "NO_COLOR": "1",
                "CI": "true",
            })

            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout, env=env,
            )

            stdout = result.stdout
            stderr = result.stderr

            # Truncate large output
            max_chars = 10_000
            if len(stdout) > max_chars:
                stdout = (
                    stdout[:max_chars // 2]
                    + f"\n...[TRUNCATED: {len(result.stdout)} chars]...\n"
                    + stdout[-max_chars // 2:]
                )
            if len(stderr) > max_chars:
                stderr = (
                    stderr[:max_chars // 2]
                    + f"\n...[TRUNCATED: {len(result.stderr)} chars]...\n"
                    + stderr[-max_chars // 2:]
                )

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s: {cmd}",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command not found: {cmd.split()[0]}",
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
            }

    def _parse_lint_issues(
        self, stdout: str, stderr: str
    ) -> List[Dict[str, Any]]:
        """
        Extract structured issues from linter output.
        Uses heuristic patterns — not linter-specific parsers.
        Works across most linters because they follow common output formats.
        """
        import re
        issues = []
        combined = stdout + "\n" + stderr
        seen = set()

        # Pattern 1: file:line:col: message (ruff, eslint, gcc, rustc, etc.)
        # Example: src/main.py:42:5: E501 line too long
        # Example: src/app.js:10:3: error  Unexpected var  no-var
        for match in re.finditer(
            r'^([^\s:]+):(\d+):(\d+):?\s*(.+)$',
            combined,
            re.MULTILINE,
        ):
            file_path = match.group(1)
            line = int(match.group(2))
            col = int(match.group(3))
            message = match.group(4).strip()

            # Skip non-source paths
            if file_path.startswith(('-', '/', '\\')) and ':' not in file_path:
                continue

            key = f"{file_path}:{line}:{message[:50]}"
            if key not in seen:
                seen.add(key)
                issues.append({
                    "file": file_path,
                    "line": line,
                    "column": col,
                    "message": message[:300],
                    "pattern": "file:line:col",
                })

        # Pattern 2: file:line: message (simpler format)
        # Example: src/main.py:42: warning: unused variable
        for match in re.finditer(
            r'^([^\s:]+):(\d+):\s*(.+)$',
            combined,
            re.MULTILINE,
        ):
            file_path = match.group(1)
            line = int(match.group(2))
            message = match.group(3).strip()

            key = f"{file_path}:{line}:{message[:50]}"
            if key not in seen:
                seen.add(key)
                issues.append({
                    "file": file_path,
                    "line": line,
                    "column": None,
                    "message": message[:300],
                    "pattern": "file:line",
                })

        # Pattern 3: "error" or "warning" anywhere in line (catch-all)
        # Only if we haven't found structured issues
        if not issues:
            for match in re.finditer(
                r'^.*(?:error|warning|Error|Warning)[:\s]+(.+)$',
                combined,
                re.MULTILINE,
            ):
                message = match.group(1).strip()
                key = f"unstructured:{message[:80]}"
                if key not in seen:
                    seen.add(key)
                    issues.append({
                        "file": None,
                        "line": None,
                        "column": None,
                        "message": message[:300],
                        "pattern": "unstructured",
                    })

        # Cap issues
        return issues[:100]

    def _count_severity(
        self, stdout: str, stderr: str
    ) -> Dict[str, int]:
        """
        Count errors vs warnings in output.
        Heuristic — looks for common severity indicators.
        """
        combined = (stdout + "\n" + stderr).lower()
        return {
            "errors": combined.count("error"),
            "warnings": combined.count("warning"),
            "info": combined.count(" info"),
            "hints": combined.count("hint") + combined.count("note:"),
        }

    def _auto_detect_lint_commands(
        self,
        available_tools: Dict[str, str],
        languages: Dict[str, int],
        repo_dir: str,
    ) -> Dict[str, str]:
        """
        Given available tools and detected languages, figure out
        which linters can be run.

        This is the ONLY place with language→linter affinity knowledge,
        and it's minimal: just "which linters work on which file types."
        The actual linter names come from the PATH scan (no hardcoding).
        """
        commands = {}

        # Build a set of available tool names (lowercase)
        tools = {k.lower(): v for k, v in available_tools.items()}

        for lang in languages:
            lang_lower = lang.lower()

            if lang_lower == "python":
                if "ruff" in tools:
                    commands["python/ruff"] = "ruff check ."
                if "mypy" in tools:
                    commands["python/mypy"] = "mypy . --ignore-missing-imports"
                if "flake8" in tools:
                    commands["python/flake8"] = "flake8 ."
                if "pylint" in tools:
                    commands["python/pylint"] = "pylint **/*.py --exit-zero"
                if "pyright" in tools:
                    commands["python/pyright"] = "pyright ."
                if "bandit" in tools:
                    commands["python/bandit"] = "bandit -r . -q"

            elif lang_lower in ("javascript", "typescript"):
                if "eslint" in tools:
                    ext = ".ts,.tsx" if lang_lower == "typescript" else ".js,.jsx"
                    commands[f"{lang_lower}/eslint"] = (
                        f"npx eslint . --ext {ext} "
                        f"--no-error-on-unmatched-pattern"
                    )
                if lang_lower == "typescript":
                    # tsc --noEmit is always available if typescript is a dep
                    tsc_path = os.path.join(
                        repo_dir, "node_modules", ".bin", "tsc"
                    )
                    if os.path.exists(tsc_path) or "tsc" in tools:
                        commands["typescript/tsc"] = "npx tsc --noEmit"

            elif lang_lower == "go":
                if "go" in tools:
                    commands["go/vet"] = "go vet ./..."
                if "golangci-lint" in tools:
                    commands["go/golangci-lint"] = "golangci-lint run ./..."

            elif lang_lower == "rust":
                if "cargo" in tools:
                    commands["rust/clippy"] = "cargo clippy -- -D warnings"
                    commands["rust/fmt"] = "cargo fmt -- --check"

            elif lang_lower in ("c", "cpp"):
                if "cppcheck" in tools:
                    lang_flag = "c++" if lang_lower == "cpp" else "c"
                    commands[f"{lang_lower}/cppcheck"] = (
                        f"cppcheck --enable=all --inconclusive "
                        f"--quiet --language={lang_flag} ."
                    )
                if "clang-tidy" in tools:
                    commands[f"{lang_lower}/clang-tidy"] = (
                        "clang-tidy *.cpp *.c 2>/dev/null || true"
                    )

            elif lang_lower == "csharp":
                if "dotnet" in tools:
                    commands["csharp/format"] = (
                        "dotnet format --verify-no-changes"
                    )

            elif lang_lower == "ruby":
                if "rubocop" in tools:
                    commands["ruby/rubocop"] = "rubocop ."

            elif lang_lower == "php":
                phpstan = os.path.join(
                    repo_dir, "vendor", "bin", "phpstan"
                )
                if os.path.exists(phpstan) or "phpstan" in tools:
                    commands["php/phpstan"] = (
                        "vendor/bin/phpstan analyse src/ --level=5"
                    )

            elif lang_lower == "java":
                # Checkstyle is usually a Maven/Gradle plugin
                pom = os.path.join(repo_dir, "pom.xml")
                if os.path.exists(pom):
                    commands["java/checkstyle"] = "mvn checkstyle:check -B"

            elif lang_lower == "kotlin":
                if "ktlint" in tools:
                    commands["kotlin/ktlint"] = "ktlint"

            elif lang_lower == "swift":
                if "swiftlint" in tools:
                    commands["swift/swiftlint"] = "swiftlint lint --quiet"

            elif lang_lower == "dart":
                if "dart" in tools:
                    commands["dart/analyze"] = "dart analyze"

            elif lang_lower == "elixir":
                if "mix" in tools:
                    commands["elixir/credo"] = "mix credo --strict"

        return commands

    async def handle_task(self, task: Task) -> AsyncGenerator[Task, None]:
        """A2A task handler for lint execution."""
        task.status = TaskStatus(state=TaskState.WORKING)
        yield task

        # Extract request data
        request_data = {}
        for part in task.history[-1].parts:
            if part.get("type") == "data":
                request_data = part["data"]

        repo_dir = request_data.get("repo_dir", self.workspace_dir)
        auto_detect = request_data.get("auto_detect", False)

        # Get lint commands — either provided or auto-detected
        lint_commands = request_data.get("commands", {})

        if not lint_commands and auto_detect:
            available_tools = request_data.get("available_tools", {})
            languages = request_data.get("languages", {})
            lint_commands = self._auto_detect_lint_commands(
                available_tools, languages, repo_dir,
            )

        if not lint_commands:
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message=Message(
                    role="agent",
                    parts=[{
                        "type": "text",
                        "text": "No lint commands to run. "
                                "Provide 'commands' dict or set 'auto_detect': true "
                                "with 'available_tools' and 'languages'.",
                    }],
                ),
            )
            task.artifacts.append(Artifact(
                name="lint_results",
                description="No linters executed",
                parts=[{
                    "type": "data",
                    "data": {
                        "executed": 0,
                        "results": {},
                    },
                }],
                index=0,
            ))
            yield task
            return

        # Execute each linter
        results = {}
        overall_passed = True
        total = len(lint_commands)
        completed = 0

        for lint_key, command in lint_commands.items():
            # Progress update
            completed += 1
            task.status = TaskStatus(
                state=TaskState.WORKING,
                message=Message(
                    role="agent",
                    parts=[{
                        "type": "text",
                        "text": f"Running linter {completed}/{total}: {lint_key}",
                    }],
                ),
            )
            yield task

            # Execute
            exec_result = self._exec(command, repo_dir)

            # Parse issues
            issues = self._parse_lint_issues(
                exec_result["stdout"], exec_result["stderr"]
            )
            severity = self._count_severity(
                exec_result["stdout"], exec_result["stderr"]
            )

            passed = exec_result["success"]
            if not passed:
                overall_passed = False

            results[lint_key] = {
                "command": command,
                "passed": passed,
                "exit_code": exec_result["exit_code"],
                "stdout": exec_result["stdout"],
                "stderr": exec_result["stderr"],
                "issues": issues,
                "issue_count": len(issues),
                "severity": severity,
            }

        # Build summary
        summary = {
            "overall_passed": overall_passed,
            "total_linters": total,
            "linters_passed": sum(
                1 for r in results.values() if r["passed"]
            ),
            "linters_failed": sum(
                1 for r in results.values() if not r["passed"]
            ),
            "total_issues": sum(
                r["issue_count"] for r in results.values()
            ),
            "total_errors": sum(
                r["severity"]["errors"] for r in results.values()
            ),
            "total_warnings": sum(
                r["severity"]["warnings"] for r in results.values()
            ),
        }

        # Results artifact
        task.artifacts.append(Artifact(
            name="lint_results",
            description="Per-linter execution results",
            parts=[{"type": "data", "data": results}],
            index=0,
        ))

        # Summary artifact
        task.artifacts.append(Artifact(
            name="lint_summary",
            description="Aggregated lint summary",
            parts=[{"type": "data", "data": summary}],
            index=1,
        ))

        # Top issues artifact (for quick reference)
        top_issues = []
        for lint_key, result in results.items():
            for issue in result["issues"][:5]:  # Top 5 per linter
                top_issues.append({
                    "linter": lint_key,
                    **issue,
                })
        task.artifacts.append(Artifact(
            name="top_issues",
            description="Most important lint issues across all linters",
            parts=[{"type": "data", "data": top_issues[:30]}],
            index=2,
        ))

        # Complete
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message(
                role="agent",
                parts=[{
                    "type": "text",
                    "text": json.dumps(summary),
                }],
            ),
        )
        yield task


# ── Agent Card Factory ────────────────────────────────────

def create_linter_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="linter",
        description=(
            "Executes static analysis linters and returns structured results. "
            "Supports any linter — just provide the command. "
            "Can auto-detect available linters from PATH scan data."
        ),
        url=f"{base_url}/agents/linter",
        skills=[
            AgentSkill(
                id="run_linters",
                name="Run Linters",
                description=(
                    "Execute provided lint commands and return structured "
                    "results with parsed issues (file, line, message)"
                ),
                tags=["linting", "static-analysis"],
                examples=[
                    '{"commands": {"python/ruff": "ruff check ."}}',
                    '{"auto_detect": true, "available_tools": {...}, "languages": {...}}',
                ],
            ),
            AgentSkill(
                id="auto_detect_linters",
                name="Auto-Detect Linters",
                description=(
                    "Given available tools on PATH and detected languages, "
                    "determine which linters can be run"
                ),
                tags=["detection", "auto-config"],
            ),
        ],
    )