# Agents Documentation

This document describes the 8 specialized AI agents defined in `src/iterative_quality_assurance_pipeline_with_test_fix_loops/config/agents.yaml` and instantiated in `crew.py`.

## 1. Repository Analyst and Task Planner
- **Role**: Understands repository structure and creates development plans.
- **Goal**: Analyzes the GitHub repository, identifies the default branch, creates a feature branch, clones it to `./workspace`, and formulates a plan.
- **Tools**: `FileReadTool`, `GitHubRepositoryInspector`, `GitHubBranchContentManager`.

## 2. Software Developer
- **Role**: Software Developer
- **Goal**: Implements clean, efficient, and well-documented code based on the development plan inside the `./workspace`.
- **Tools**: `FileReadTool`, `GitHubRepositoryInspector`, `BashExecutionTool`, `FileWriteTool`.
- **Apps**: `github/get_file`

## 3. Test Strategy Designer
- **Role**: Test Strategy Designer
- **Goal**: Designs comprehensive testing strategies and test plans (Unit, Integration, E2E) for the newly implemented code.
- **Tools**: `FileReadTool`.

## 4. Test Implementation Engineer
- **Role**: Test Implementation Engineer
- **Goal**: Writes the actual automated test scripts based on the test strategy inside `./workspace`.
- **Tools**: `FileReadTool`, `BashExecutionTool`, `FileWriteTool`.

## 5. Test Execution Specialist
- **Role**: Test Execution Specialist
- **Goal**: Executes tests systematically using shell commands (`BashExecutionTool`), gathers execution data, and analyzes failures.
- **Tools**: `FileReadTool`, `BashExecutionTool`.

## 6. QA Report Generator
- **Role**: QA Report Generator
- **Goal**: Synthesizes all execution data into a professional, comprehensive Quality Assurance report.
- **Tools**: `FileReadTool`.

## 7. GitHub Integration Specialist
- **Role**: GitHub Integration Specialist
- **Goal**: Manages the final repository operations. It commits and pushes the `./workspace` changes to the remote feature branch, and opens a Pull Request to merge the changes.
- **Tools**: `GitHubRepositoryInspector`, `GitHubBranchContentManager`, `GitHubBranchValidator`, `FileReadTool`.
- **Apps**: `github/create_issue`, `github/create_release`, `github/get_file`

## 8. Iterative Test and Fix Specialist (The Core Engine)
- **Role**: Iterative Test and Fix Specialist
- **Goal**: Acts as the autonomous debugger. It runs tests, identifies failing code, implements fixes locally, and re-validates. It loops until all identified issues are resolved.
- **Tools**: `FileReadTool`, `GitHubRepositoryInspector`, `BashExecutionTool`, `FileWriteTool`.
