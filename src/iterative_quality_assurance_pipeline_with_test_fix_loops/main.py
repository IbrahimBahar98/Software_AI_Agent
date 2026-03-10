#!/usr/bin/env python
"""Entry point for the Iterative QA Pipeline crew."""

# Force UTF-8 mode before any other imports
import os
os.environ.setdefault("PYTHONUTF8", "1")

import sys
import re
import platform
import argparse
import atexit
from datetime import datetime

# Ensure MCP server processes are cleaned up on exit
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.mcp_bridge_tool import cleanup_all_mcp_servers
atexit.register(cleanup_all_mcp_servers)



def validate_github_url(url: str) -> str:
    """Normalize and validate GitHub repository URL."""
    url = url.strip().rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]
    if re.match(r'^[\w.-]+/[\w.-]+$', url):
        url = f"https://github.com/{url}"
    pattern = r'^https://github\.com/[\w.-]+/[\w.-]+$'
    if not re.match(pattern, url):
        raise ValueError(
            f"Invalid GitHub URL: '{url}'\n"
            f"Expected: https://github.com/owner/repo"
        )
    return url


def _build_os_context(repo_abs_path: str) -> str:
    """Build OS-specific context instructions for agents."""
    common = (
        f"CRITICAL: The repository absolute path is: {repo_abs_path}\n"
        f"You MUST prepend this path to all filenames for file read/write/execute operations.\n"
        f"Example: '{repo_abs_path}{os.sep}package.json'"
    )
    if platform.system() == "Windows":
        return (
            f"WORKSPACE CONTEXT: Windows machine, PowerShell. "
            f"Use backslashes (\\) for paths. Use non-interactive flags (-y, --yes, -q). "
            f"{common}"
        )
    return (
        f"WORKSPACE CONTEXT: Unix-like system, Bash. "
        f"Use POSIX commands and forward slashes (/). "
        f"{common}"
    )


def _default_inputs() -> dict:
    """Shared default inputs for train/test/replay modes."""
    from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR
    return {
        'github_repo_url': 'https://github.com/test-org/sample-repo',
        'requirements': 'Add unit tests for core modules',
        'branch_name': 'feature/test-run',
        'default_branch': 'main',
        'timestamp': datetime.now().strftime("%Y%m%d-%H%M%S"),
        'os_context': _build_os_context(REPO_DIR),
        'repo_abs_path': REPO_DIR,
        'max_fix_iterations': 5,
    }


def _authenticate_github() -> str:
    """Handle GitHub authentication, supporting both interactive and CI modes."""
    existing = os.environ.get("GITHUB_AUTH_TKN")
    if existing:
        print("[\033[92m✓\033[0m] Using existing GITHUB_AUTH_TKN from environment.")
        return existing

    if not sys.stdin.isatty():
        print("[\033[91mX\033[0m] GITHUB_AUTH_TKN not set and running non-interactively. Exiting.")
        sys.exit(1)

    print("\n--- GitHub Authentication ---")
    from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.github_oauth_tool import GitHubOAuthTool
    token = GitHubOAuthTool().get_or_request_token_interactive()
    if not token:
        print("[\033[91mX\033[0m] Authentication failed. Exiting.")
        sys.exit(1)
    return token


def run():
    """Run the crew with CLI arguments or interactive prompts."""
    if os.name == 'nt':
        os.system('chcp 65001 > nul')
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass

    from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
        REPO_DIR, MAX_FIX_ITERATIONS
    )
    from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import (
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew
    )

    parser = argparse.ArgumentParser(description="Run the QA pipeline")
    parser.add_argument("--repo_url", type=str, help="GitHub repository URL")
    parser.add_argument("--requirements", type=str, help="Requirements for the agents")
    parser.add_argument("--branch_name", type=str, default=None)
    parser.add_argument("--default_branch", type=str, default="main")
    args = parser.parse_args(sys.argv[2:])

    if not args.repo_url:
        args.repo_url = input("GitHub repository URL: ").strip()
    if not args.requirements:
        args.requirements = input("What should the agents do? ").strip()

    args.repo_url = validate_github_url(args.repo_url)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if not args.branch_name:
        args.branch_name = f"feature/agent-update-{timestamp}"

    github_tkn = _authenticate_github()
    os.environ["GITHUB_AUTH_TKN"] = github_tkn

    inputs = {
        "github_repo_url": args.repo_url,
        "requirements": args.requirements,
        "branch_name": args.branch_name,
        "default_branch": args.default_branch,
        "timestamp": timestamp,
        "os_context": _build_os_context(REPO_DIR),
        "repo_abs_path": REPO_DIR,
        "max_fix_iterations": MAX_FIX_ITERATIONS,
    }

    print(f"\nPipeline starting...")
    print(f"  Repo:   {inputs['github_repo_url']}")
    print(f"  Branch: {inputs['branch_name']}")
    print(f"  Path:   {inputs['repo_abs_path']}")
    print()

    pipeline = IterativeQualityAssurancePipelineWithTestFixLoopsCrew()
    try:
        result = pipeline.crew().kickoff(inputs=inputs)

        print("\n" + "=" * 60)
        print("PIPELINE COMPLETED")
        print("=" * 60)

        os.makedirs(os.path.dirname(REPO_DIR), exist_ok=True)
        output_path = os.path.join(os.path.dirname(REPO_DIR), "pipeline_result.md")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(result))
        print(f"Result: {output_path}")

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
        sys.exit(130)
    except Exception as e:
        import traceback
        print(f"\n[\033[91mX\033[0m] Pipeline failed: {e}")
        error_path = os.path.join(os.path.dirname(REPO_DIR), "pipeline_error.log")
        os.makedirs(os.path.dirname(error_path), exist_ok=True)
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"Failed: {datetime.now().isoformat()}\n")
            f.write(f"Inputs: {inputs}\n\n")
            traceback.print_exc(file=f)
        print(f"Error log: {error_path}")
        sys.exit(1)
    finally:
        if hasattr(pipeline, 'logger'):
            pipeline.logger.finish_run()


def train():
    """Train the crew for N iterations."""
    if len(sys.argv) < 4:
        print("Usage: main.py train <n_iterations> <output_filename>")
        sys.exit(1)
    from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import (
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew
    )
    n_iterations = int(sys.argv[2])
    filename = sys.argv[3]
    inputs = _default_inputs()
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().train(
            n_iterations=n_iterations, filename=filename, inputs=inputs
        )
    except Exception as e:
        raise Exception(f"Training failed: {e}")


def replay():
    """Replay from a specific task."""
    if len(sys.argv) < 3:
        print("Usage: main.py replay <task_id>")
        sys.exit(1)
    from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import (
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew
    )
    task_id = sys.argv[2]
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().replay(task_id=task_id)
    except Exception as e:
        raise Exception(f"Replay failed: {e}")


def test():
    """Test the crew execution."""
    if len(sys.argv) < 4:
        print("Usage: main.py test <n_iterations> <model_name>")
        sys.exit(1)
    from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import (
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew
    )
    n_iterations = int(sys.argv[2])
    model_name = sys.argv[3]
    inputs = _default_inputs()
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().test(
            n_iterations=n_iterations, openai_model_name=model_name, inputs=inputs
        )
    except Exception as e:
        raise Exception(f"Test failed: {e}")


if __name__ == "__main__":
    commands = {"run": run, "train": train, "replay": replay, "test": test}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: main.py <{'|'.join(commands)}> [args]")
        sys.exit(1)
    commands[sys.argv[1]]()