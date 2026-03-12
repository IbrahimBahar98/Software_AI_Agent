# a2a/agents/fixer_agent.py
"""
Fixer Agent — receives test failures and applies targeted fixes.
Communicates fix results back via A2A artifacts.
"""

import os
import json
import logging
from typing import Dict, Any, AsyncGenerator, List
from pathlib import Path

from ..models import (
    AgentCard, AgentSkill, Task, TaskState, TaskStatus,
    Message, Artifact,
)

logger = logging.getLogger(__name__)


class FixerAgent:
    """
    Receives structured failure data and coordinates fixes.
    This agent doesn't fix code itself — it structures the problem
    for an LLM-powered CrewAI agent to solve.
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self._fix_history: List[Dict] = []

    def _read_file_context(
        self, file_path: str, line: int, context_lines: int = 20
    ) -> Dict[str, Any]:
        """Read file context around a failure line."""
        full_path = os.path.join(self.workspace_dir, file_path)

        if not os.path.exists(full_path):
            # Try absolute path
            if os.path.exists(file_path):
                full_path = file_path
            else:
                return {
                    "error": f"File not found: {file_path}",
                    "file_path": file_path,
                }

        try:
            lines = Path(full_path).read_text(
                encoding='utf-8', errors='ignore'
            ).split('\n')

            start = max(0, line - context_lines - 1)
            end = min(len(lines), line + context_lines)

            return {
                "file_path": file_path,
                "absolute_path": full_path,
                "total_lines": len(lines),
                "focus_line": line,
                "context_start": start + 1,
                "context_end": end,
                "context": '\n'.join(
                    f"{i + 1:4d} | {lines[i]}"
                    for i in range(start, end)
                ),
            }
        except Exception as e:
            return {
                "error": f"Failed to read {file_path}: {e}",
                "file_path": file_path,
            }

    def _build_fix_plan(
        self, failures: List[Dict], test_output: str
    ) -> List[Dict]:
        """
        Analyze failures and build a structured fix plan.
        Groups related failures, prioritizes, and provides context.
        """
        fix_items = []
        seen_files = set()

        for failure in failures:
            file_path = failure.get("file")
            line = failure.get("line")

            if not file_path:
                continue

            # Deduplicate by file
            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            # Read context
            context = {}
            if line:
                context = self._read_file_context(file_path, line)

            fix_items.append({
                "priority": len(fix_items) + 1,
                "file": file_path,
                "line": line,
                "failure_info": failure,
                "file_context": context,
                "suggested_approach": self._suggest_approach(failure, test_output),
            })

        return fix_items[:10]  # Cap at 10 per cycle

    def _suggest_approach(
        self, failure: Dict, test_output: str
    ) -> str:
        """Suggest a fix approach based on failure patterns."""
        test_info = failure.get("test", "")
        output_lower = test_output.lower()

        if "import" in output_lower and "not found" in output_lower:
            return "Missing import — add the required import statement"
        if "undefined" in output_lower or "is not defined" in output_lower:
            return "Undefined variable/function — check spelling or add definition"
        if "assertionerror" in output_lower or "expect" in output_lower:
            return "Assertion failure — check expected vs actual values in source code"
        if "typeerror" in output_lower:
            return "Type error — check argument types and return values"
        if "syntaxerror" in output_lower:
            return "Syntax error — check for missing brackets, semicolons, etc."
        if "timeout" in output_lower:
            return "Timeout — check for infinite loops or missing async/await"
        if "connection" in output_lower:
            return "Connection error — mock external dependencies in tests"
        if "permission" in output_lower:
            return "Permission error — check file permissions or use temp directories"

        return "Review the error output and fix the root cause in source code"

    def _check_if_stuck(
        self, file_path: str, cycle: int
    ) -> bool:
        """Check if we've tried fixing this file too many times."""
        attempts = sum(
            1 for h in self._fix_history
            if h.get("file") == file_path
        )
        return attempts >= 3

    async def handle_task(self, task: Task) -> AsyncGenerator[Task, None]:
        """A2A task handler for fix analysis."""
        task.status = TaskStatus(state=TaskState.WORKING)
        yield task

        # Extract request data
        request_data = {}
        for part in task.history[-1].parts:
            if part.get("type") == "data":
                request_data = part["data"]

        test_results = request_data.get("test_results", {})
        cycle = request_data.get("cycle", 1)
        max_cycles = request_data.get("max_cycles", 5)

        all_fix_plans = {}
        has_failures = False

        for lang, result in test_results.items():
            if result.get("success", True) or result.get("skipped", False):
                continue

            has_failures = True
            failures = result.get("failures", [])
            test_output = result.get("stdout", "") + "\n" + result.get("stderr", "")

            # Filter out stuck files
            active_failures = [
                f for f in failures
                if not self._check_if_stuck(f.get("file", ""), cycle)
            ]

            if not active_failures and failures:
                all_fix_plans[lang] = {
                    "status": "stuck",
                    "message": (
                        f"All {len(failures)} failures have been attempted "
                        f"3+ times. Consider skipping or manual review."
                    ),
                    "stuck_files": [f.get("file") for f in failures],
                }
                continue

            fix_plan = self._build_fix_plan(active_failures, test_output)

            # Record in history
            for item in fix_plan:
                self._fix_history.append({
                    "file": item["file"],
                    "cycle": cycle,
                    "lang": lang,
                })

            all_fix_plans[lang] = {
                "status": "needs_fix",
                "fix_count": len(fix_plan),
                "fixes": fix_plan,
                "raw_output_snippet": test_output[:2000],
            }

        if not has_failures:
            task.artifacts.append(Artifact(
                name="fix_plan",
                description="No fixes needed — all tests pass",
                parts=[{"type": "data", "data": {"status": "all_passing"}}],
                index=0,
            ))
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message=Message(
                    role="agent",
                    parts=[{"type": "text", "text": "All tests passing. No fixes needed."}],
                ),
            )
            yield task
            return

        # Output fix plan
        task.artifacts.append(Artifact(
            name="fix_plan",
            description="Structured fix plan with file contexts",
            parts=[{"type": "data", "data": all_fix_plans}],
            index=0,
        ))

        # Cycle status
        cycle_status = {
            "current_cycle": cycle,
            "max_cycles": max_cycles,
            "languages_needing_fixes": len(all_fix_plans),
            "total_fixes_planned": sum(
                p.get("fix_count", 0) for p in all_fix_plans.values()
            ),
            "stuck_languages": [
                lang for lang, plan in all_fix_plans.items()
                if plan.get("status") == "stuck"
            ],
        }
        task.artifacts.append(Artifact(
            name="cycle_status",
            description="Fix loop cycle tracking",
            parts=[{"type": "data", "data": cycle_status}],
            index=1,
        ))

        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message(
                role="agent",
                parts=[{
                    "type": "text",
                    "text": json.dumps(cycle_status),
                }],
            ),
        )
        yield task


def create_fixer_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="fixer",
        description=(
            "Analyzes test failures and creates structured fix plans. "
            "Tracks fix history to detect stuck loops."
        ),
        url=f"{base_url}/agents/fixer",
        skills=[
            AgentSkill(
                id="analyze_failures",
                name="Failure Analysis",
                description="Parse test output, extract failures, read source context",
                tags=["debugging", "analysis"],
            ),
            AgentSkill(
                id="track_fixes",
                name="Fix Tracking",
                description="Track fix attempts per file to detect stuck loops",
                tags=["tracking", "loop-detection"],
            ),
        ],
    )