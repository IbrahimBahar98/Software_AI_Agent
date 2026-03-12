# a2a/agents/test_runner_agent.py
"""
Test Runner Agent — receives discovery results and runs tests.
Communicates results back via A2A artifacts.
"""

import os
import json
import subprocess
import logging
from typing import Dict, Any, AsyncGenerator, Optional

from ..models import (
    AgentCard, AgentSkill, Task, TaskState, TaskStatus,
    Message, Artifact,
)

logger = logging.getLogger(__name__)


class TestRunnerAgent:
    """
    Runs tests based on discovery artifacts.
    Doesn't hardcode any language knowledge — uses command mappings
    from the Discovery Agent.
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    def _exec(
        self, cmd: str, cwd: str, timeout: int = 300
    ) -> Dict[str, Any]:
        """Execute a shell command."""
        try:
            env = os.environ.copy()
            env.update({
                "CI": "true",
                "PYTHONUNBUFFERED": "1",
                "FORCE_COLOR": "0",
                "NO_COLOR": "1",
            })

            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout, env=env,
            )

            stdout = result.stdout
            stderr = result.stderr
            # Truncate large output
            max_chars = 20_000
            if len(stdout) > max_chars:
                stdout = stdout[:max_chars // 2] + "\n...[TRUNCATED]...\n" + stdout[-max_chars // 2:]
            if len(stderr) > max_chars:
                stderr = stderr[:max_chars // 2] + "\n...[TRUNCATED]...\n" + stderr[-max_chars // 2:]

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
                "stderr": f"Timed out after {timeout}s",
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
            }

    def _parse_test_failures(
        self, stdout: str, stderr: str, lang: str
    ) -> list:
        """
        Extract structured failure info from test output.
        Language-aware but heuristic-based, not hardcoded formats.
        """
        failures = []
        combined = stdout + "\n" + stderr

        # Common patterns across frameworks
        import re

        # Pattern: FAILED test_name - message
        for match in re.finditer(
            r'(?:FAIL|FAILED|ERROR|FAILURE)[:\s]+(.+?)(?:\n|$)',
            combined
        ):
            failures.append({
                "test": match.group(1).strip()[:200],
                "type": "test_failure",
            })

        # Pattern: File "path", line N
        for match in re.finditer(
            r'File "([^"]+)",\s*line (\d+)',
            combined
        ):
            failures.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "type": "traceback",
            })

        # Pattern: at Object.<anonymous> (path:line:col) — JavaScript
        for match in re.finditer(
            r'at\s+\S+\s+\(([^:]+):(\d+):\d+\)',
            combined
        ):
            failures.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "type": "traceback",
            })

        # Pattern: filename.java:NN — Java
        for match in re.finditer(
            r'(\w+\.java):(\d+)',
            combined
        ):
            failures.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "type": "traceback",
            })

        # Deduplicate
        seen = set()
        unique = []
        for f in failures:
            key = json.dumps(f, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return unique[:20]  # Cap at 20

    async def handle_task(self, task: Task) -> AsyncGenerator[Task, None]:
        """A2A task handler for test execution."""
        task.status = TaskStatus(state=TaskState.WORKING)
        yield task

        # Extract request data
        request_data = {}
        for part in task.history[-1].parts:
            if part.get("type") == "data":
                request_data = part["data"]

        repo_dir = request_data.get("repo_dir", self.workspace_dir)
        command_mappings = request_data.get("command_mappings", {})
        test_commands = command_mappings.get("test_commands", {})
        coverage_commands = command_mappings.get("coverage_commands", {})
        languages = request_data.get("languages", list(test_commands.keys()))
        with_coverage = request_data.get("with_coverage", True)
        specific_language = request_data.get("language")  # Run only one language

        if specific_language:
            languages = [specific_language]

        results = {}
        overall_success = True

        for lang in languages:
            # Choose command
            cmd = None
            if with_coverage and lang in coverage_commands:
                cmd = coverage_commands[lang]
            elif lang in test_commands:
                cmd = test_commands[lang]

            if not cmd:
                results[lang] = {
                    "skipped": True,
                    "reason": f"No test command for {lang}",
                }
                continue

            # Progress update
            task.status = TaskStatus(
                state=TaskState.WORKING,
                message=Message(
                    role="agent",
                    parts=[{
                        "type": "text",
                        "text": f"Running {lang} tests: {cmd}",
                    }],
                ),
            )
            yield task

            # Execute
            exec_result = self._exec(cmd, repo_dir)

            # Parse failures
            failures = []
            if not exec_result["success"]:
                overall_success = False
                failures = self._parse_test_failures(
                    exec_result["stdout"],
                    exec_result["stderr"],
                    lang,
                )

            results[lang] = {
                "command": cmd,
                "success": exec_result["success"],
                "exit_code": exec_result["exit_code"],
                "stdout": exec_result["stdout"],
                "stderr": exec_result["stderr"],
                "failures": failures,
                "failure_count": len(failures),
            }

        # Build result artifact
        task.artifacts.append(Artifact(
            name="test_results",
            description="Test execution results per language",
            parts=[{"type": "data", "data": results}],
            index=0,
        ))

        # Summary artifact
        summary = {
            "overall_success": overall_success,
            "languages_tested": len(results),
            "languages_passed": sum(
                1 for r in results.values()
                if r.get("success", False)
            ),
            "languages_failed": sum(
                1 for r in results.values()
                if not r.get("success", True) and not r.get("skipped", False)
            ),
            "total_failures": sum(
                r.get("failure_count", 0) for r in results.values()
            ),
        }
        task.artifacts.append(Artifact(
            name="test_summary",
            description="Aggregated test summary",
            parts=[{"type": "data", "data": summary}],
            index=1,
        ))

        task.status = TaskStatus(
            state=TaskState.COMPLETED if overall_success else TaskState.COMPLETED,
            message=Message(
                role="agent",
                parts=[{"type": "text", "text": json.dumps(summary)}],
            ),
        )
        yield task


# ── Agent Card factory ────────────────────────────────────

def create_test_runner_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="test-runner",
        description=(
            "Executes tests based on discovery results. "
            "Supports any language — uses command mappings from discovery agent."
        ),
        url=f"{base_url}/agents/test-runner",
        skills=[
            AgentSkill(
                id="run_tests",
                name="Run Tests",
                description="Execute test suites with structured failure parsing",
                tags=["testing", "execution"],
            ),
            AgentSkill(
                id="run_coverage",
                name="Run Coverage",
                description="Execute tests with coverage tracking",
                tags=["testing", "coverage"],
            ),
        ],
    )