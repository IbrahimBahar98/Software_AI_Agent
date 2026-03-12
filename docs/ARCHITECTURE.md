# Project Architecture

The **Iterative Quality Assurance Pipeline** is built on top of the [CrewAI](https://crewai.com) framework. It automates the software development lifecycle (SDLC) from requirements analysis to testing, iterative bug fixing, and GitHub pull request creation.

## System Components

1. **Crew (`crew.py`)**: The central orchestrator. It defines the AI agents, the tasks they perform, and the sequential process by which they operate.
2. **Agents (`config/agents.yaml`)**: The "employees" of the system. Each agent has a specific role (e.g., Software Developer, QA Analyst), goal, backstory, and a set of allowed tools.
3. **Tasks (`config/tasks.yaml`)**: The specific jobs assigned to the agents. Tasks define the expected output and sequence.
4. **Tools (`tools/`)**: Custom Python classes that allow the agents to interact with the outside world.
5. **A2A Server (`src/a2a/`)**: Background server providing discovery, testing, and fixing capabilities for agents.
6. **LLM Integration**: The pipeline uses an OpenAI-compatible API endpoint (configured for DashScope/Qwen via `.env`), managing LLM usage centrally from `config.py`.

## Execution Flow (The Process)

The process runs using CrewAI's `Process.sequential` strategy. Agents work in a defined sequence, sharing state through the `CheckpointTool` and leveraging a background A2A (Agent-to-Agent) server for specialized repository tasks.

1. **Setup & Planning**: The system clones the target GitHub repository into a local `./workspace` directory and creates a development plan, analyzing existing CI configuration via `ci_config_reader_tool`.
2. **Implementation**: Code modifications are made directly to the local files.
3. **Test Design & Implementation**: Automated test scripts (e.g., `pytest`) are generated based on the implementation.
4. **Iterative Test/Fix Loop**: 
   - A fast `lint_gate_tool` executes first. If syntax is invalid, it loops immediately.
   - If linting passes, `pytest` executes locally.
   - If tests fail, an iterative fixing agent uses `patch_apply_tool` to apply targeted unified diff patches without rewriting massive files.
   - This loop explicitly caps out at 5 iterations to halt runaway LLM costs.
5. **Reporting & PR Creation**: A final QA report is generated, local changes are committed/pushed to the remote feature branch, and a GitHub Pull Request is opened automatically.
6. **Observability**: Throughout this entire flow, the `run_logger.py` collects step-level telemetry, including tool calls and estimated token counts, saving a structured `.run_log_{timestamp}.json` in your workspace.

## Workspace Management

The pipeline operates almost exclusively on a local `./workspace` directory to avoid destructive changes to the original repository. 
- Agents use the `BashExecutionTool` to run tests and linters in this directory.
- Agents use the `FileWriteTool` to update code inside this directory.
- The `GitHubBranchContentManager` uses `git` commands inside this directory to push changes back to origin.
