"""
Shell execution tool for the QA pipeline.
Runs commands in PowerShell (Windows) or Bash (Unix).
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess
import platform
import os
import json
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_BASH_TIMEOUT, MAX_BASH_OUTPUT_CHARS
)

IS_WINDOWS = platform.system() == "Windows"


class BashExecutionInput(BaseModel):
    """Input schema for Bash Execution Tool."""
    command: str = Field(..., description="The shell command to execute in the workspace.")


class BashExecutionTool(BaseTool):
    """Tool for executing shell commands in the workspace."""

    name: str = "bash_execution_tool"
    description: str = (
        "Executes a shell command (PowerShell on Windows, Bash on Linux/macOS) within the "
        "repository root directory. CRITICAL: This tool is locked to the repository root. "
        "'cd' alone has no effect between calls — combine with commands: "
        "'cd subdir && npm test'. On Windows, use non-interactive flags "
        "(-y, --yes, -q) to prevent hanging. "
        "The working directory is always the repository root."
    )
    args_schema: Type[BaseModel] = BashExecutionInput
    workspace_dir: str = REPO_DIR

    def __init__(self, workspace_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if workspace_dir:
            self.workspace_dir = os.path.abspath(workspace_dir)
        else:
            self.workspace_dir = REPO_DIR

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

    def _extract_command_prefix(self, command: str) -> str:
        """
        Extract the first meaningful command prefix, handling:
          - ENV=value prefix: CI=true npm test → npm
          - cd ... && cmd: cd subdir && npm test → cd
          - path prefix: ./gradlew → gradlew
          - quoted commands
        """
        cmd = command.strip()
        if not cmd:
            return ""

        # Strip leading environment variable assignments (FOO=bar cmd)
        parts = cmd.split()
        idx = 0
        while idx < len(parts) and "=" in parts[idx] and not parts[idx].startswith("-"):
            # Looks like ENV=value
            if parts[idx].split("=")[0].replace("_", "").isalpha():
                idx += 1
            else:
                break

        if idx < len(parts):
            prefix = parts[idx]
        else:
            prefix = parts[0]

        # Clean up
        prefix = prefix.replace("./", "").replace(".\\", "").strip('"').strip("'")
        return prefix

    def _run(self, command: str) -> str:
        """Execute the requested shell command."""
        os_name = platform.system()

        # ── Security: Blocklist ──
        blocked_patterns = [
            "rm -rf /", "rm -rf ~", "mkfs", "dd if=", "format C:",
            "shutdown", "reboot", ":(){", "curl|sh", "wget|sh",
            "> /dev/sd", "chmod -R 777 /",
            "Remove-Item -Recurse -Force C:", "Format-Volume",
            "Stop-Computer", "Restart-Computer",
            "shutil.rmtree('/')", "os.remove('/')",
        ]
        if any(bad in command for bad in blocked_patterns):
            return json.dumps({
                "success": False,
                "error": "Blocked: Command contains forbidden patterns."
            })

        # ── Security: Allowlist ──
        allowed_prefixes = {
            # Python
            "pytest", "python", "python3", "pip", "pip3", "uv",
            "ruff", "mypy", "flake8", "black", "isort", "pylint", "coverage",
            # JavaScript/TypeScript
            "npm", "npx", "node", "yarn", "pnpm",
            "vitest", "cypress", "jest", "mocha", "eslint", "tsc", "prettier",
            # Java
            "mvn", "mvn.cmd", "gradle", "gradlew", "gradle.bat",
            "javac", "java", "jar",
            # C/C++
            "make", "cmake", "ctest", "gcc", "g++", "clang", "clang++",
            "cppcheck", "clang-tidy", "gcov", "lcov",
            # Rust
            "cargo", "rustc", "clippy", "rustfmt", "rustup",
            # Go
            "go", "gofmt", "golangci-lint",
            # C#/.NET
            "dotnet", "csc", "nuget",
            # Ruby
            "ruby", "rspec", "bundle", "rake", "rubocop", "gem",
            # PHP
            "php", "phpunit", "composer", "phpstan",
            # Shell/Filesystem (cross-platform)
            "cd", "ls", "dir", "cat", "type", "echo", "mkdir", "pwd",
            "find", "head", "tail", "sed", "grep", "wc", "sort", "uniq",
            "cp", "mv", "rm", "touch", "chmod", "which", "where",
            "tree", "du", "df", "env", "export", "set",
            "tar", "unzip", "curl", "wget", "git",
            # Windows-specific
            "Get-ChildItem", "New-Item", "Remove-Item", "Test-Path",
            "Select-String", "Get-Content", "Set-Content",
            "Write-Output", "Invoke-Expression",
            "chcp", "more", "findstr", "xcopy", "robocopy", "icacls",
            "powershell", "cmd", "cmd.exe",
        }

        prefix = self._extract_command_prefix(command)
        if prefix and prefix not in allowed_prefixes:
            return json.dumps({
                "success": False,
                "error": (
                    f"Command prefix '{prefix}' is not in the allowed list. "
                    f"If this is a valid tool, it may need to be added to the allowlist."
                )
            })

        # ── Ensure workspace exists ──
        cwd = self.workspace_dir
        if not os.path.exists(cwd):
            try:
                os.makedirs(cwd, exist_ok=True)
            except Exception:
                pass

        # ── Environment for non-interactive behavior ──
        env = os.environ.copy()
        env["CI"] = "true"
        env["CONTINUOUS_INTEGRATION"] = "true"
        env["PIP_NO_INPUT"] = "on"
        env["NPM_CONFIG_YES"] = "true"
        env["PYTHONUNBUFFERED"] = "1"
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["FORCE_COLOR"] = "0"
        env["NO_COLOR"] = "1"

        try:
            if IS_WINDOWS:
                # && and || are CMD operators, not PowerShell
                if "&&" in command or "||" in command:
                    shell_args = ["cmd.exe", "/c", command]
                    use_shell = False
                else:
                    shell_args = [
                        "powershell", "-NoProfile",
                        "-NonInteractive", "-Command", command
                    ]
                    use_shell = False
            else:
                shell_args = command
                use_shell = True

            result = subprocess.run(
                shell_args,
                shell=use_shell,
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
                    "stderr": self._truncate_output(result.stderr, "stderr"),
                })

            # ── Windows CMD fallback ──
            if IS_WINDOWS:
                error_lower = result.stderr.lower()
                ps_errors = [
                    "executionpolicy", "not recognized",
                    "cannot be loaded", "is not a valid cmdlet",
                    "is not recognized as a cmdlet",
                ]
                if any(err in error_lower for err in ps_errors):
                    fallback = subprocess.run(
                        ["cmd.exe", "/c", command],
                        cwd=cwd, env=env,
                        capture_output=True, text=True,
                        timeout=MAX_BASH_TIMEOUT
                    )
                    return json.dumps({
                        "success": fallback.returncode == 0,
                        "os": f"{os_name} (CMD Fallback)",
                        "exit_code": fallback.returncode,
                        "stdout": self._truncate_output(fallback.stdout, "stdout"),
                        "stderr": self._truncate_output(fallback.stderr, "stderr"),
                    })

            return json.dumps({
                "success": False,
                "os": os_name,
                "exit_code": result.returncode,
                "stdout": self._truncate_output(result.stdout, "stdout"),
                "stderr": self._truncate_output(result.stderr, "stderr"),
            })

        except subprocess.TimeoutExpired:
            return json.dumps({
                "success": False,
                "error": f"Command timed out after {MAX_BASH_TIMEOUT} seconds.",
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to execute: {type(e).__name__}: {e}",
            })