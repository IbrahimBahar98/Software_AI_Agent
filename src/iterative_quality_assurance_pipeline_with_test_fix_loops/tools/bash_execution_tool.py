from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_BASH_TIMEOUT, MAX_BASH_OUTPUT_CHARS
)


class BashExecutionInput(BaseModel):
    """Input schema for Bash Execution Tool."""
    command: str = Field(..., description="The shell command to execute in the workspace.")


class BashExecutionTool(BaseTool):
    """Tool for executing bash commands in the local workspace."""

    name: str = "bash_execution_tool"
    description: str = (
        "Executes a shell command (PowerShell on Windows, Bash on Linux) within the "
        "repository root directory. CRITICAL: This tool is permanently locked to the "
        "repository root. 'cd' alone has no effect between calls — combine with other "
        "commands: 'cd subdir && npm test'. On Windows, use non-interactive flags "
        "(-y, --yes, -q, --quiet) to prevent hanging."
    )
    args_schema: Type[BaseModel] = BashExecutionInput
    workspace_dir: str = REPO_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        super().__init__(**kwargs)
        self.workspace_dir = REPO_DIR

    def _get_os_info(self):
        import platform
        return platform.system()

    def _truncate_output(self, text: str, label: str = "output") -> str:
        """Truncate output while preserving head and tail."""
        if len(text) <= MAX_BASH_OUTPUT_CHARS:
            return text
        half = MAX_BASH_OUTPUT_CHARS // 2
        return (
            f"{text[:half]}\n\n"
            f"... [{label} TRUNCATED: {len(text)} chars total, "
            f"showing first/last {half} chars] ...\n\n"
            f"{text[-half:]}"
        )

    def _run(self, command: str) -> str:
        """Execute the requested shell command with auto-fallback."""
        os_name = self._get_os_info()
        is_windows = os_name == "Windows"

        # Security: Blocklist of dangerous commands
        blocked_commands = [
            "rm -rf /", "rm -rf ~", "mkfs", "dd if=", "format C:",
            "shutdown", "reboot", ":(){", "curl|sh", "wget|sh",
            "> /dev/sd", "chmod -R 777 /",
            "Remove-Item -Recurse -Force C:", "Format-Volume",
            "Stop-Computer", "Restart-Computer",
            "shutil.rmtree('/')", "os.remove('/')",
        ]
        if any(bad in command for bad in blocked_commands):
            return json.dumps({
                "success": False,
                "error": f"Blocked: Command contains forbidden patterns."
            })

        # Security: Allowlist of command prefixes
        allowed_prefixes = [
            "pytest", "python", "python3", "pip", "pip3",
            "ruff", "mypy", "flake8", "black", "isort", "pylint",
            "npm", "npx", "node", "yarn", "pnpm",
            "git", "ls", "cat", "echo", "mkdir", "pwd", "find",
            "head", "tail", "sed", "grep", "wc", "sort", "uniq",
            "dir", "Get-ChildItem", "New-Item", "Remove-Item", "Test-Path",
            "vitest", "cypress", "jest", "mocha", "eslint", "tsc",
            "mvn", "gradle", "gradlew", "./gradlew",
            "make", "cmake", "ctest", "gcc", "g++", "clang", "clang++",
            "cargo", "rustc", "clippy",
            "go", "gofmt", "golangci-lint",
            "dotnet", "csc",
            "ruby", "rspec", "bundle", "rake",
            "php", "phpunit", "composer",
            "javac", "java", "jar",
            "cppcheck", "clang-tidy", "gcov", "lcov",
            "cd", "cp", "mv", "rm", "touch", "chmod", "which", "type",
            "tree", "du", "df", "env", "export", "set",
            "tar", "unzip", "curl", "wget",
        ]
        cmd_prefix = command.split()[0].replace("./", "") if command.strip() else ""
        if cmd_prefix and cmd_prefix not in allowed_prefixes:
            return json.dumps({
                "success": False,
                "error": f"Command prefix '{cmd_prefix}' is not in the allowed list. "
                         f"Allowed: {', '.join(sorted(set(allowed_prefixes)))}"
            })

        # Ensure workspace exists
        if not os.path.exists(self.workspace_dir):
            try:
                os.makedirs(self.workspace_dir, exist_ok=True)
            except Exception:
                pass

        cwd = self.workspace_dir

        # Environment for non-interactive behavior
        env = os.environ.copy()
        env["CI"] = "true"
        env["CONTINUOUS_INTEGRATION"] = "true"
        env["PIP_NO_INPUT"] = "on"
        env["NPM_CONFIG_YES"] = "true"
        env["PYTHONUNBUFFERED"] = "1"
        env["DEBIAN_FRONTEND"] = "noninteractive"

        try:
            if is_windows:
                shell_args = ["powershell", "-Command", command]
            else:
                shell_args = command

            result = subprocess.run(
                shell_args,
                shell=(not is_windows),
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=MAX_BASH_TIMEOUT
            )

            if result.returncode == 0:
                return json.dumps({
                    "success": True,
                    "os": os_name,
                    "exit_code": result.returncode,
                    "stdout": self._truncate_output(result.stdout, "stdout"),
                    "stderr": self._truncate_output(result.stderr, "stderr")
                })

            # Windows CMD fallback
            error_msg = result.stderr.lower()
            critical_errors = [
                "executionpolicy", "not recognized",
                "cannot be loaded", "is not a valid cmdlet"
            ]

            if is_windows and any(err in error_msg for err in critical_errors):
                cmd_args = ["cmd.exe", "/c", command]
                fallback_result = subprocess.run(
                    cmd_args, cwd=cwd, env=env,
                    capture_output=True, text=True, timeout=MAX_BASH_TIMEOUT
                )
                return json.dumps({
                    "success": fallback_result.returncode == 0,
                    "os": f"{os_name} (CMD Fallback)",
                    "exit_code": fallback_result.returncode,
                    "stdout": self._truncate_output(fallback_result.stdout),
                    "stderr": self._truncate_output(fallback_result.stderr),
                })

            return json.dumps({
                "success": False,
                "os": os_name,
                "exit_code": result.returncode,
                "stdout": self._truncate_output(result.stdout),
                "stderr": self._truncate_output(result.stderr)
            })

        except subprocess.TimeoutExpired:
            return json.dumps({
                "success": False,
                "error": f"Command timed out after {MAX_BASH_TIMEOUT} seconds."
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to execute command: {str(e)}"
            })
