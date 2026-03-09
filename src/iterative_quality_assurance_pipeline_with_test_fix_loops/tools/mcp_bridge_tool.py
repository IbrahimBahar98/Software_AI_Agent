import os
import json
import subprocess
import sys
import time
from typing import Type, Optional, Dict, Any, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

class MCPToolInput(BaseModel):
    """Input for MCP tools."""
    server_name: str = Field(..., description="The name of the MCP server to call (github, puppeteer, sequential-thinking)")
    method: str = Field(..., description="The MCP tool method to call (e.g., 'github_search_code', 'puppeteer_screenshot')")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the MCP tool")

class MCPBridgeTool(BaseTool):
    """Generic bridge to interact with MCP servers via stdio using npx."""
    
    name: str = "mcp_bridge_tool"
    description: str = (
        "Interactive bridge to MCP servers (GitHub, Puppeteer, Sequential Thinking). "
        "Allows calling specialized tools like 'puppeteer_screenshot', 'github_search_code', etc. "
        "Usage: Provide server_name, method, and arguments."
    )
    args_schema: Type[BaseModel] = MCPToolInput

    def _get_server_command(self, server_name: str) -> List[str]:
        """Maps server name to npx command."""
        mapping = {
            "github": ["-y", "@modelcontextprotocol/server-github"],
            "puppeteer": ["-y", "@modelcontextprotocol/server-puppeteer"],
            "sequential-thinking": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
        }
        if server_name not in mapping:
            raise ValueError(f"Unknown MCP server: {server_name}")
        return ["npx"] + mapping[server_name]

    def _run(self, server_name: str, method: str, arguments: Dict[str, Any]) -> str:
        """Runs an MCP tool call via stdio JSON-RPC."""
        
        # Setup environment (GitHub needs token)
        env = os.environ.copy()
        if server_name == "github":
            # Prioritize GITHUB_AUTH_TKN which we already set up in main.py
            token = os.getenv("GITHUB_AUTH_TKN")
            if not token:
                # Fallback to .env directly if not already in env
                from dotenv import load_dotenv
                load_dotenv()
                token = os.getenv("GITHUB_AUTH_TKN")
            
            if token:
                env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token

        try:
            cmd = self._get_server_command(server_name)
            
            # Start the process
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1
            )
            
            # MCP Initialization (Simplified for one-shot CLI use)
            # In a full MCP implementation, we'd do a handshake. 
            # For npx-based servers, we send the call and wait.
            
            # Check for immediate failure
            if process.poll() is not None:
                stderr = process.stderr.read()
                return f"❌ Failed to start MCP server {server_name}: {stderr}"

            # Prepare JSON-RPC request
            # Note: MCP uses a specific 'tools/call' method
            request = {
                "jsonrpc": "2.0",
                "id": int(time.time()),
                "method": f"tools/call",
                "params": {
                    "name": method,
                    "arguments": arguments
                }
            }
            
            # Send request
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            
            # Read response (Wait with timeout)
            # This is a simplified stdio reader
            output = ""
            start_wait = time.time()
            while True:
                if time.time() - start_wait > 30: # 30s timeout
                    process.terminate()
                    return f"❌ Timeout waiting for MCP {server_name}/{method}"
                
                line = process.stdout.readline()
                if line:
                    output += line
                    try:
                        resp = json.loads(output)
                        if "id" in resp:
                            break
                    except json.JSONDecodeError:
                        continue
                
                if process.poll() is not None:
                    break
            
            process.terminate()
            
            if not output:
                return f"❌ Error: MCP server {server_name} exited without response."

            resp = json.loads(output)
            if "error" in resp:
                return f"❌ MCP Error: {json.dumps(resp['error'])}"
            
            # Standard MCP result extraction
            result = resp.get("result", {})
            content = result.get("content", [])
            
            # Format output for the agent
            formatted_outputs = []
            for item in content:
                if item.get("type") == "text":
                    formatted_outputs.append(item.get("text", ""))
                elif item.get("type") == "image":
                    formatted_outputs.append("[Image data received - saved to workspace/outputs/]")
            
            return "\n".join(formatted_outputs) if formatted_outputs else json.dumps(result, indent=2)

        except Exception as e:
            return f"❌ MCP Bridge Error: {str(e)}"
