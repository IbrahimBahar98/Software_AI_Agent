"""
MCP Bridge Tool — connects CrewAI agents to MCP servers via stdio JSON-RPC.

Supported servers:
  - github: Repository search, code search, issues, file contents
  - puppeteer: Browser automation, screenshots
  - sequential-thinking: Step-by-step reasoning
"""
import os
import json
import subprocess
import shutil
import sys
import time
import threading
import itertools
import base64
import logging
from typing import Type, Optional, Dict, Any, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    WORKSPACE_DIR, MAX_MCP_TIMEOUT
)

logger = logging.getLogger(__name__)

_request_counter = itertools.count(1)
_MCP_PROCESS_CACHE: Dict[str, subprocess.Popen] = {}
_MCP_INITIALIZED: Dict[str, bool] = {}
_MCP_STDERR_THREADS: Dict[str, threading.Thread] = {}
_MCP_STDERR_LINES: Dict[str, list] = {}

# Max buffer size for JSON-RPC response parsing
_MAX_BUFFER_SIZE = 100_000


class MCPToolInput(BaseModel):
    """Input for MCP tools."""
    server_name: str = Field(
        ...,
        description="MCP server: 'github', 'puppeteer', or 'sequential-thinking'"
    )
    method: str = Field(
        ...,
        description=(
            "MCP tool method. Examples:\n"
            "  github: search_repositories, search_code, get_file_contents, "
            "list_issues, create_issue\n"
            "  puppeteer: puppeteer_navigate, puppeteer_screenshot, "
            "puppeteer_click, puppeteer_fill\n"
            "  sequential-thinking: create_thinking_process"
        )
    )
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments dict for the method call."
    )


class MCPBridgeTool(BaseTool):
    """Bridge to MCP servers via stdio JSON-RPC."""

    name: str = "mcp_bridge_tool"
    description: str = (
        "Bridge to MCP (Model Context Protocol) servers. Available servers:\n"
        "- github: search_repositories, search_code, get_file_contents, "
        "list_issues, create_issue\n"
        "- puppeteer: puppeteer_navigate, puppeteer_screenshot, "
        "puppeteer_click, puppeteer_fill\n"
        "- sequential-thinking: create_thinking_process\n"
        "Provide server_name, method, and arguments dict."
    )
    args_schema: Type[BaseModel] = MCPToolInput

    # ── Server command mapping ────────────────────────────

    _SERVER_PACKAGES: Dict[str, str] = {
        "github": "@modelcontextprotocol/server-github",
        "puppeteer": "@modelcontextprotocol/server-puppeteer",
        "sequential-thinking": "@modelcontextprotocol/server-sequential-thinking",
    }

    def _get_server_command(self, server_name: str) -> List[str]:
        """Get the npx command to start an MCP server."""
        if server_name not in self._SERVER_PACKAGES:
            raise ValueError(
                f"Unknown MCP server: '{server_name}'. "
                f"Available: {list(self._SERVER_PACKAGES.keys())}"
            )

        # Verify npx is available
        npx_path = shutil.which("npx")
        if not npx_path:
            raise RuntimeError(
                "npx not found on PATH. Install Node.js first: "
                "https://nodejs.org/"
            )

        package = self._SERVER_PACKAGES[server_name]
        return [npx_path, "-y", package]

    # ── Process management ────────────────────────────────

    def _drain_stderr(self, server_name: str, process: subprocess.Popen):
        """Read stderr in background to prevent pipe deadlock."""
        lines = _MCP_STDERR_LINES.setdefault(server_name, [])
        try:
            for line in process.stderr:
                lines.append(line)
                if len(lines) > 200:
                    lines.pop(0)
        except Exception:
            pass

    def _get_stderr_output(self, server_name: str) -> str:
        """Get accumulated stderr for a server."""
        lines = _MCP_STDERR_LINES.get(server_name, [])
        return "".join(lines[-20:])  # Last 20 lines

    def _read_response(
        self,
        process: subprocess.Popen,
        timeout: int = None,
        expected_id: int = None,
    ) -> Optional[dict]:
        """Read a JSON-RPC response, skipping notifications."""
        if timeout is None:
            timeout = MAX_MCP_TIMEOUT
        start = time.time()
        buffer = ""

        while time.time() - start < timeout:
            try:
                line = process.stdout.readline()
            except Exception:
                break

            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue

            # Try standalone JSON first
            try:
                msg = json.loads(line)
                buffer = ""  # Reset buffer on successful parse
            except json.JSONDecodeError:
                buffer += line
                # Safety: prevent buffer from growing too large
                if len(buffer) > _MAX_BUFFER_SIZE:
                    logger.warning("MCP response buffer exceeded max size, resetting")
                    buffer = ""
                    continue
                try:
                    msg = json.loads(buffer)
                    buffer = ""
                except json.JSONDecodeError:
                    continue

            # Skip notifications (no "id" field)
            if "id" not in msg:
                continue

            if expected_id is not None and msg["id"] != expected_id:
                continue

            return msg

        return None

    def _initialize_server(self, process: subprocess.Popen) -> bool:
        """Perform MCP protocol initialization handshake."""
        init_id = next(_request_counter)
        init_request = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "crewai-mcp-bridge", "version": "1.0"}
            }
        }

        try:
            process.stdin.write(json.dumps(init_request) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error(f"Failed to write init request: {e}")
            return False

        init_response = self._read_response(process, timeout=15, expected_id=init_id)
        if not init_response or "error" in init_response:
            logger.error(f"MCP init failed: {init_response}")
            return False

        # Send initialized notification
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            process.stdin.write(json.dumps(notification) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error(f"Failed to send initialized notification: {e}")
            return False

        return True

    def _get_or_start_server(self, server_name: str, env: dict) -> subprocess.Popen:
        """Get cached server process or start a new one."""
        global _MCP_PROCESS_CACHE, _MCP_INITIALIZED

        # Check cached process
        if server_name in _MCP_PROCESS_CACHE:
            proc = _MCP_PROCESS_CACHE[server_name]
            if proc.poll() is None:
                return proc
            # Process died
            logger.warning(f"MCP server '{server_name}' died, restarting...")
            del _MCP_PROCESS_CACHE[server_name]
            _MCP_INITIALIZED.pop(server_name, None)

        cmd = self._get_server_command(server_name)
        logger.info(f"Starting MCP server '{server_name}': {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )

        # Start stderr drain thread
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(server_name, proc),
            daemon=True,
        )
        stderr_thread.start()
        _MCP_STDERR_THREADS[server_name] = stderr_thread

        # Check for immediate failure
        time.sleep(0.5)
        if proc.poll() is not None:
            stderr_output = self._get_stderr_output(server_name)
            raise RuntimeError(
                f"MCP server '{server_name}' exited immediately.\n"
                f"Stderr: {stderr_output[:500]}"
            )

        # Initialize
        if not self._initialize_server(proc):
            _cleanup_process(proc)
            stderr_output = self._get_stderr_output(server_name)
            raise RuntimeError(
                f"MCP initialization failed for '{server_name}'.\n"
                f"Stderr: {stderr_output[:500]}"
            )

        _MCP_PROCESS_CACHE[server_name] = proc
        _MCP_INITIALIZED[server_name] = True
        logger.info(f"MCP server '{server_name}' initialized successfully")
        return proc

    # ── Main execution ────────────────────────────────────

    def _run(self, server_name: str, method: str, arguments: Dict[str, Any]) -> str:
        """Runs an MCP tool call via stdio JSON-RPC."""

        env = os.environ.copy()
        if server_name == "github":
            token = os.getenv("GITHUB_AUTH_TKN")
            if not token:
                return json.dumps({
                    "success": False,
                    "error": (
                        "GITHUB_AUTH_TKN not set. "
                        "Authentication should be handled at startup."
                    )
                })
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token

        try:
            process = self._get_or_start_server(server_name, env)

            request_id = next(_request_counter)
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": method,
                    "arguments": arguments,
                }
            }

            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                # Server died mid-request, remove from cache and report
                _MCP_PROCESS_CACHE.pop(server_name, None)
                _MCP_INITIALIZED.pop(server_name, None)
                return json.dumps({
                    "success": False,
                    "error": f"MCP server '{server_name}' pipe broken: {e}. Retry the call."
                })

            resp = self._read_response(
                process, timeout=MAX_MCP_TIMEOUT, expected_id=request_id
            )

            if not resp:
                _MCP_PROCESS_CACHE.pop(server_name, None)
                _MCP_INITIALIZED.pop(server_name, None)
                stderr_output = self._get_stderr_output(server_name)
                return json.dumps({
                    "success": False,
                    "error": (
                        f"MCP server '{server_name}' did not respond within "
                        f"{MAX_MCP_TIMEOUT}s for method '{method}'.\n"
                        f"Stderr: {stderr_output[:300]}"
                    )
                })

            if "error" in resp:
                return json.dumps({
                    "success": False,
                    "error": f"MCP Error: {json.dumps(resp['error'])}"
                })

            # Format response content
            result = resp.get("result", {})
            content = result.get("content", [])

            formatted = []
            for item in content:
                item_type = item.get("type", "")
                if item_type == "text":
                    formatted.append(item.get("text", ""))
                elif item_type == "image":
                    image_data = item.get("data", "")
                    if image_data:
                        output_dir = os.path.join(
                            WORKSPACE_DIR, "outputs", "screenshots"
                        )
                        os.makedirs(output_dir, exist_ok=True)
                        filename = f"screenshot_{int(time.time())}.png"
                        filepath = os.path.join(output_dir, filename)
                        try:
                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(image_data))
                            formatted.append(f"[Screenshot saved: {filepath}]")
                        except Exception as e:
                            formatted.append(f"[Screenshot save failed: {e}]")
                    else:
                        formatted.append("[Empty image data]")
                elif item_type == "resource":
                    # Some MCP servers return resource references
                    formatted.append(
                        f"[Resource: {item.get('uri', 'unknown')}]"
                    )

            return "\n".join(formatted) if formatted else json.dumps(result, indent=2)

        except RuntimeError as e:
            return json.dumps({"success": False, "error": str(e)})
        except Exception as e:
            _MCP_PROCESS_CACHE.pop(server_name, None)
            _MCP_INITIALIZED.pop(server_name, None)
            logger.error(f"MCP Bridge unexpected error: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"MCP Bridge Error: {type(e).__name__}: {e}"
            })


# ── Module-level cleanup (no instance needed) ────────────

def _cleanup_process(proc: subprocess.Popen):
    """Gracefully shut down a single MCP server process."""
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass


def cleanup_all_mcp_servers():
    """Call on pipeline shutdown to clean up all cached MCP processes."""
    for name, proc in list(_MCP_PROCESS_CACHE.items()):
        logger.info(f"Cleaning up MCP server: {name}")
        _cleanup_process(proc)
    _MCP_PROCESS_CACHE.clear()
    _MCP_INITIALIZED.clear()
    _MCP_STDERR_THREADS.clear()
    _MCP_STDERR_LINES.clear()
