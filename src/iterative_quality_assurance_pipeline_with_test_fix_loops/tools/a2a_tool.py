"""
A2A Bridge Tool — allows CrewAI agents to communicate with A2A agents.

Self-contained: does NOT import from the a2a package.
Uses httpx directly for HTTP calls.
Falls back gracefully if A2A server is not running.
"""

import json
import logging
import os
import uuid
from typing import Type, Dict, Any
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

logger = logging.getLogger(__name__)

# Optional dependency — tool works without it (returns helpful error)
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class A2AToolInput(BaseModel):
    """Input for A2A agent communication."""
    agent_name: str = Field(
        ...,
        description=(
            "Target A2A agent: 'discovery', 'test-runner', 'fixer', 'linter'"
        ),
    )
    message: str = Field(
        ...,
        description="Natural language request to the agent.",
    )
    data: str = Field(
        default="{}",
        description="JSON string with structured data to pass.",
    )


class A2ATool(BaseTool):
    """Bridge between CrewAI agents and A2A protocol agents."""

    name: str = "a2a_tool"
    description: str = (
        "Communicate with specialized A2A agents for discovery and analysis.\n"
        "Available agents:\n"
        "- 'discovery': Discover OS, languages, frameworks, tools in repo\n"
        "- 'test-runner': Execute tests for any language\n"
        "- 'fixer': Analyze test failures and suggest fixes\n"
        "- 'linter': Run language-appropriate linters\n"
        "Provide agent_name, message, and data (JSON string).\n"
        "Example: agent_name='discovery', message='Analyze repo', "
        "data='{\"repo_dir\": \"/path/to/repo\"}'"
    )
    args_schema: Type[BaseModel] = A2AToolInput

    def _get_base_url(self) -> str:
        """Get A2A server URL from environment."""
        return os.environ.get("A2A_BASE_URL", "http://localhost:5000")

    def _check_server(self, base_url: str) -> bool:
        """Quick check if A2A server is reachable."""
        if not HTTPX_AVAILABLE:
            return False
        try:
            resp = httpx.get(
                f"{base_url}/.well-known/agent.json",
                timeout=3,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _send_task(
        self,
        base_url: str,
        agent_name: str,
        message: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a task to an A2A agent via HTTP."""
        parts = [{"type": "text", "text": message}]
        if data:
            parts.append({"type": "data", "data": data})

        request_body = {
            "id": str(uuid.uuid4()),
            "params": {
                "message": {
                    "role": "user",
                    "parts": parts,
                },
            },
        }

        resp = httpx.post(
            f"{base_url}/agents/{agent_name}/tasks/send",
            json=request_body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def _extract_response(self, task_data: Dict[str, Any]) -> str:
        """Extract useful content from A2A task response."""
        response = {
            "success": task_data.get("status", {}).get("state") == "completed",
            "state": task_data.get("status", {}).get("state", "unknown"),
            "artifacts": {},
            "message": "",
        }

        # Extract artifacts
        for artifact in task_data.get("artifacts", []):
            artifact_content = {}
            for part in artifact.get("parts", []):
                if part.get("type") == "data":
                    artifact_content.update(part["data"])
                elif part.get("type") == "text":
                    artifact_content["text"] = part["text"]
            name = artifact.get("name", "unnamed")
            response["artifacts"][name] = artifact_content

        # Extract status message
        status_msg = task_data.get("status", {}).get("message")
        if status_msg and isinstance(status_msg, dict):
            for part in status_msg.get("parts", []):
                if part.get("type") == "text":
                    response["message"] = part["text"]

        return json.dumps(response, indent=2)

    def _fallback_message(self, agent_name: str, error: str) -> str:
        """Return helpful fallback instructions when A2A is unavailable."""
        fallbacks = {
            "discovery": (
                "A2A discovery unavailable. Discover manually:\n"
                "1. Use bash_execution_tool to list files and extensions\n"
                "2. Use bash_execution_tool to check tool versions "
                "(python --version, node --version, etc.)\n"
                "3. Use file_read_tool to read config files "
                "(package.json, pyproject.toml, etc.)\n"
                "4. Save findings to checkpoint_tool"
            ),
            "test-runner": (
                "A2A test-runner unavailable. Run tests manually:\n"
                "1. Read checkpoint for test commands\n"
                "2. Use bash_execution_tool to run them\n"
                "3. Parse output for pass/fail"
            ),
            "linter": (
                "A2A linter unavailable. Run linters manually:\n"
                "1. Check what linters are available: "
                "which ruff, which eslint, etc.\n"
                "2. Run them via bash_execution_tool\n"
                "3. Parse output for errors"
            ),
            "fixer": (
                "A2A fixer unavailable. Analyze failures manually:\n"
                "1. Read test output for error messages\n"
                "2. Use file_read_tool to read failing source files\n"
                "3. Apply fixes with file_write_tool"
            ),
        }

        return json.dumps({
            "success": False,
            "error": error,
            "fallback": fallbacks.get(agent_name, (
                "Use bash_execution_tool and file_read_tool "
                "as alternatives."
            )),
        })

    def _run(self, agent_name: str, message: str, data: str = "{}") -> str:
        """Send a task to an A2A agent and return the result."""

        # Parse data
        try:
            parsed_data = json.loads(data)
        except json.JSONDecodeError:
            parsed_data = {"raw": data}

        # Check httpx available
        if not HTTPX_AVAILABLE:
            return self._fallback_message(
                agent_name,
                "httpx package not installed. Install: pip install httpx"
            )

        base_url = self._get_base_url()

        # Check server available
        if not self._check_server(base_url):
            return self._fallback_message(
                agent_name,
                f"A2A server not reachable at {base_url}. "
                f"Server may not be running (--no_a2a flag or startup failure)."
            )

        # Send task
        try:
            task_result = self._send_task(
                base_url, agent_name, message, parsed_data,
            )
            return self._extract_response(task_result)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return self._fallback_message(
                    agent_name,
                    f"A2A agent '{agent_name}' not found on server. "
                    f"Available agents may differ."
                )
            return self._fallback_message(
                agent_name,
                f"A2A HTTP error: {e.response.status_code} {e.response.text[:200]}"
            )

        except httpx.TimeoutException:
            return self._fallback_message(
                agent_name,
                f"A2A request to '{agent_name}' timed out after 120s."
            )

        except Exception as e:
            logger.error(f"A2A tool error: {e}", exc_info=True)
            return self._fallback_message(
                agent_name,
                f"A2A failed: {type(e).__name__}: {e}"
            )