import os
import json
import subprocess
import sys
import time
import threading
import itertools
import base64
from typing import Type, Optional, Dict, Any, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    WORKSPACE_DIR, MAX_MCP_TIMEOUT
)

_request_counter = itertools.count(1)
_MCP_PROCESS_CACHE: Dict[str, subprocess.Popen] = {}
_MCP_INITIALIZED: Dict[str, bool] = {}


class MCPToolInput(BaseModel):
    """Input for MCP tools."""
    server_name: str = Field(..., description="MCP server: 'github', 'puppeteer', or 'sequential-thinking'")
    method: str = Field(..., description="MCP tool method (e.g., 'search_repositories', 'puppeteer_screenshot', 'create_thinking_process')")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the method")


class MCPBridgeTool(BaseTool):
    """Bridge to MCP servers via stdio JSON-RPC."""

    name: str = "mcp_bridge_tool"
    description: str = (
        "Bridge to MCP servers. Available servers and methods:\n"
        "- github: search_repositories, search_code, get_file_contents, list_issues, create_issue\n"
        "- puppeteer: puppeteer_navigate, puppeteer_screenshot, puppeteer_click, puppeteer_fill\n"
        "- sequential-thinking: create_thinking_process\n"
        "Provide server_name, method, and arguments dict."
    )
    args_schema: Type[BaseModel] = MCPToolInput

    def _get_server_command(self, server_name: str) -> List[str]:
        mapping = {
            "github": ["-y", "@modelcontextprotocol/server-github"],
            "puppeteer": ["-y", "@modelcontextprotocol/server-puppeteer"],
            "sequential-thinking": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
        }
        if server_name not in mapping:
            raise ValueError(f"Unknown MCP server: {server_name}. Available: {list(mapping.keys())}")
        return ["npx"] + mapping[server_name]

    def _drain_stderr(self, process: subprocess.Popen, container: list):
        """Read stderr in background to prevent pipe deadlock."""
        try:
            for line in process.stderr:
                container.append(line)
                if len(container) > 200:
                    container.pop(0)
        except Exception:
            pass

    def _read_response(self, process: subprocess.Popen, timeout: int = None,
                       expected_id: int = None) -> Optional[dict]:
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

            # Try to parse as standalone JSON
            try:
                msg = json.loads(line)
                buffer = ""
            except json.JSONDecodeError:
                buffer += line
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
        except Exception:
            return False

        init_response = self._read_response(process, timeout=15, expected_id=init_id)
        if not init_response or "error" in init_response:
            return False

        # Send initialized notification
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            process.stdin.write(json.dumps(notification) + "\n")
            process.stdin.flush()
        except Exception:
            return False

        return True

    def _get_or_start_server(self, server_name: str, env: dict) -> subprocess.Popen:
        """Get cached server process or start a new one."""
        global _MCP_PROCESS_CACHE, _MCP_INITIALIZED

        if server_name in _MCP_PROCESS_CACHE:
            proc = _MCP_PROCESS_CACHE[server_name]
            if proc.poll() is None:
                return proc
            # Process died, remove from cache
            del _MCP_PROCESS_CACHE[server_name]
            _MCP_INITIALIZED.pop(server_name, None)

        cmd = self._get_server_command(server_name)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1
        )

        # Start stderr drain thread
        stderr_lines = []
        stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(proc, stderr_lines), daemon=True
        )
        stderr_thread.start()

        # Check for immediate failure
        time.sleep(0.5)
        if proc.poll() is not None:
            stderr_output = "".join(stderr_lines)
            raise RuntimeError(f"MCP server {server_name} exited immediately: {stderr_output[:500]}")

        # Initialize
        if not self._initialize_server(proc):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            stderr_output = "".join(stderr_lines)
            raise RuntimeError(f"MCP init failed for {server_name}: {stderr_output[:500]}")

        _MCP_PROCESS_CACHE[server_name] = proc
        _MCP_INITIALIZED[server_name] = True
        return proc

    def _cleanup_process(self, process: subprocess.Popen):
        """Gracefully shut down an MCP server process."""
        try:
            process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass

    def _run(self, server_name: str, method: str, arguments: Dict[str, Any]) -> str:
        """Runs an MCP tool call via stdio JSON-RPC."""

        env = os.environ.copy()
        if server_name == "github":
            token = os.getenv("GITHUB_AUTH_TKN")
            if not token:
                return json.dumps({
                    "success": False,
                    "error": "GITHUB_AUTH_TKN not set. Authentication should be handled at startup."
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
                    "arguments": arguments
                }
            }

            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()

            resp = self._read_response(process, timeout=MAX_MCP_TIMEOUT, expected_id=request_id)

            if not resp:
                # Server may have died, remove from cache
                _MCP_PROCESS_CACHE.pop(server_name, None)
                _MCP_INITIALIZED.pop(server_name, None)
                return f"Error: MCP server {server_name} did not respond within {MAX_MCP_TIMEOUT}s for method '{method}'"

            if "error" in resp:
                return f"MCP Error: {json.dumps(resp['error'])}"

            result = resp.get("result", {})
            content = result.get("content", [])

            formatted = []
            for item in content:
                if item.get("type") == "text":
                    formatted.append(item.get("text", ""))
                elif item.get("type") == "image":
                    image_data = item.get("data", "")
                    if image_data:
                        output_dir = os.path.join(WORKSPACE_DIR, "outputs", "screenshots")
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
                        formatted.append("[Empty image data received]")

            return "\n".join(formatted) if formatted else json.dumps(result, indent=2)

        except RuntimeError as e:
            return f"MCP Bridge Error: {str(e)}"
        except Exception as e:
            _MCP_PROCESS_CACHE.pop(server_name, None)
            _MCP_INITIALIZED.pop(server_name, None)
            return f"MCP Bridge Error: {str(e)}"


def cleanup_all_mcp_servers():
    """Call on pipeline shutdown to clean up all cached MCP processes."""
    bridge = MCPBridgeTool()
    for name, proc in list(_MCP_PROCESS_CACHE.items()):
        bridge._cleanup_process(proc)
    _MCP_PROCESS_CACHE.clear()
    _MCP_INITIALIZED.clear()