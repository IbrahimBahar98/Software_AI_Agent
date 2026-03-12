# Changelog

All notable changes to the Iterative Quality Assurance Pipeline will be documented in this file.

## [1.2.0] - 2026-03-08

### Added: Generic Self-Healing Terminal & Absolute Path Anchoring

This update addresses the "Working Directory Desync" and implements a fallback strategy to handle Windows-specific terminal execution blocks.

#### 1. Smart Auto-Fallback (Self-Healing)
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/tools/bash_execution_tool.py`
- **Change**: Implemented a retry loop for command execution.
- **Detail**: If a command fails in PowerShell with an execution policy or "not recognized" error, the tool automatically retries the command wrapped in `cmd.exe /c`.

#### 2. Absolute Workspace Anchoring
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/config.py`
- **Change**: `WORKSPACE_DIR` now resolves to an absolute path immediately.
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/tools/bash_execution_tool.py` & `file_write_tool.py`
- **Detail**: Both tools now strictly use the absolute `WORKSPACE_DIR` for their `cwd` and path resolution, preventing agents from creating files outside the repository.

#### 3. Troubleshooting Protocol
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/main.py`
- **Change**: Added a 3-step recovery protocol to the agent `os_context`.
- **Detail**: Agents are now instructed on how to recover from "File not found" errors and "Execution policy" blocks by verifying paths and using `cmd /c`.

#### 4. Working Directory Rules 
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/config/tasks.yaml`
- **Change**: Prepended "CRITICAL: All operations must occur within the repository root workspace" to all core development and testing tasks.

## [1.1.0] - 2026-03-08

### Fixed: Windows "OS Identity Crisis" & Terminal Compatibility

This update resolves critical issues where CrewAI agents defaulted to Linux/Bash commands on Windows and terminal output was garbled.

#### 1. Command Execution (PowerShell Integration)
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/tools/bash_execution_tool.py`
- **Change**: Updated `BashExecutionTool` to dynamically detect the operating system.
- **Detail**: On Windows, the tool now explicitly uses `powershell.exe -Command` to execute instructions, ensuring compatibility with the VS Code integrated terminal environment.

#### 2. Dynamic Agent Context (OS-Specific Instructions)
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/main.py`
- **Change**: Implemented an `os_context` detection and injection system.
- **Detail**: The pipeline now determines if it's running on Windows or Linux/Mac and prepares a strict "Workspace Context" string. This string forces agents to use PowerShell commands (e.g., `Get-ChildItem` instead of `ls`) and provides guidance on Windows path handling.

#### 3. Agent Backstory Placeholders
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/config/agents.yaml`
- **Change**: Added `{os_context}` placeholders to all relevant agent backstories.
- **Detail**: This allows CrewAI to automatically interpolate the OS-specific instructions into the agents' system prompts, eliminating their "Linux-by-default" behavior.

#### 4. Path Handling & Escape Sequences
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/main.py`
- **Change**: Enhanced the `os_context` instructions.
- **Detail**: Added explicit directives for agents to use backslashes (`\`) for Windows paths and to correctly use escape sequences (like `\\`) or raw strings in Python/Shell commands to avoid path-related errors.

#### 5. Terminal Rendering (UTF-8)
- **File**: `src/iterative_quality_assurance_pipeline_with_test_fix_loops/main.py`
- **Change**: Forced system-level UTF-8 encoding.
- **Detail**: Added `os.system('chcp 65001 > nul')` and reconfigured `sys.stdout`/`sys.stderr` to use UTF-8. This ensures that emojis, checkmarks, and UI separators are rendered correctly on Windows terminals without causing `UnicodeEncodeError`.
