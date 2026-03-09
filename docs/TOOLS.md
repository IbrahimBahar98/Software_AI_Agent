# Custom Tools Documentation

The pipeline relies on a suite of custom Python tools located in `src/iterative_quality_assurance_pipeline_with_test_fix_loops/tools/`. These tools bridge the gap between the AI Agents and actual execution on the host machine.

## 1. BashExecutionTool (`bash_execution_tool.py`)
- **Purpose**: Allows agents to run terminal commands on the user's local machine.
- **Security Mechanism**: Uses a strict blocklist (blocks `rm -rf`, `mkfs`, `dd`, etc.) and a safelist prefix warning system (`pytest`, `python`, `npm`, `git`, etc.) to heuristically block or warn about dangerous operations.
- **Use Cases**: Used heavily for running linters (`ruff`, `flake8`), static type checkers (`mypy`), and test runners (`pytest`, `npm run test`) inside the local `./workspace`.

## 2. FileWriteTool (`file_write_tool.py`)
- **Purpose**: A safer alternative to bash file redirection (like `echo > file`).
- **Format**: Takes an absolute file path and raw text content as arguments. If the directory does not exist, it creates it.
- **Use Cases**: Used by the Software Developer and iterative fixing agents to create or completely overwrite python files inside the `./workspace` safely without escaping issues.

## 3. GitHubRepositoryInspector (`github_repository_inspector.py`)
- **Purpose**: Read-only GitHub API interactions.
- **Authentication**: Requires the `GITHUB_AUTH_TKN` environment variable.
- **Use Cases**: Retrieves repository metadata (default branch, owner, description), checks if branches exist, gets commit histories, and fetches specific file contents directly from GitHub.

## 4. GitHubOAuthTool (`github_oauth_tool.py`)
- **Purpose**: Handles one-click browser-based authentication (VS Code style).
- **Security**: Starts a temporary local server on `http://localhost:8080` to securely catch the OAuth code from GitHub.
- **Use Cases**: Used at startup to verify the user has a valid authenticated session. Replaces manual PAT (Personal Access Token) generation.

## 5. GitHubBranchContentManager (`github_branch_content_manager.py`)
- **Purpose**: Write-oriented operations for GitHub and Git manipulation.
- **Authentication**: Requires the `GITHUB_AUTH_TKN` environment variable.
- **Capabilities**:
  1. `get_repo_info`: Gets default branch data.
  2. `create_branch`: Spawns a new branch using the GitHub API rather than local git.
  3. `clone_repo`: Executes a `git clone` using the auth token embedded in the URL to bypass git credential managers locally.
  4. `commit_and_push`: Executes `git add .`, `git commit`, and `git push` on the local `./workspace` folder.
  5. `create_pr`: Validates source and target branches, then posts to the GitHub `/pulls` endpoint, logging HTTP 422 constraints if PRs already exist.

## 6. LintGateTool (`lint_gate_tool.py`)
- **Purpose**: Fast pre-check static analysis using `ruff` and `mypy` natively.
- **Use Cases**: Used by the Test Execution Specialist to catch syntax errors and missing imports *before* running `pytest`. Returns structured JSON of errors, allowing the pipeline to immediately loop back to the fix agent and saving LLM tokens from massive pytest crash dumps.

## 7. PatchApplyTool (`patch_apply_tool.py`)
- **Purpose**: A precision file editing tool using unified diffs (`patch`).
- **Use Cases**: Replaces the full-file overwrite `FileWriteTool` on the fixing agent. Ensures that the AI only edits the specific failing lines instead of recreating entire large files, which prevents token exhaustion and accidental data loss. It automatically falls back to `git apply` if standard `patch` is missing.

## 8. CheckpointTool (`checkpoint_tool.py`)
- **Purpose**: Persists the current state and progress to `.pipeline_state.json`.
- **Use Cases**: Marks milestones like "tests passed" or "branch created" so the pipeline can safely recover or resume without starting from scratch if interrupted.

## 9. TestCoverageTool (`test_coverage_tool.py`)
- **Purpose**: Runs `pytest --cov --cov-fail-under=70`.
- **Use Cases**: Used by the Test Execution Specialist to compute coverage metrics. Ensures the pipeline loops to build more tests if code coverage is lacking.

## 10. CIConfigReaderTool (`ci_config_reader_tool.py`)
- **Purpose**: Parses existing GitHub Action workflows (`.github/workflows/*.yml`).
- **Use Cases**: Grants the Test Strategy Designer vision into upstream testing dependencies, Python runtime requirements, and existing bash configurations used in the project's real CI pipeline.

## 12. MCPBridgeTool (`mcp_bridge_tool.py`)
- **Purpose**: Provides a unified interface to specialized Model Context Protocol (MCP) servers using `npx`.
- **Integrations**:
  1. **GitHub MCP**: Extended search, issue, and PR management tools.
  2. **Puppeteer MCP**: Enables browser-based UI testing and screenshots.
  3. **Sequential Thinking**: Helps agents structure complex reasoning into logical steps.
- **Use Cases**: Used by the Analyst to research code, the Tester to verify UI changes, and the Fix Specialist to debug complex logic loops.
