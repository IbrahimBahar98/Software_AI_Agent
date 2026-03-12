#!/usr/bin/env python
"""Entry point for the Iterative QA Pipeline crew."""

import os
os.environ.setdefault("PYTHONUTF8", "1")

from dotenv import load_dotenv
load_dotenv()

import sys
import re
import platform
import argparse
import atexit
import threading
import time
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")

# Cleanup MCP servers on exit
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.mcp_bridge_tool import cleanup_all_mcp_servers
atexit.register(cleanup_all_mcp_servers)


# ── Validation ────────────────────────────────────────────

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
            f"Expected: https://github.com/owner/repo or owner/repo"
        )
    return url


# ── Environment Context Builder ───────────────────────────
# Minimal — tells agents HOW to discover, not WHAT exists

def _build_env_context(repo_abs_path: str) -> str:
    """
    Build minimal environment context.
    Does NOT list commands or tools — agents discover those via A2A.
    Only provides the essential facts agents need to start working.
    """
    system = platform.system()

    context = (
        f"ENVIRONMENT:\n"
        f"  OS: {system} ({platform.release()})\n"
        f"  Architecture: {platform.machine()}\n"
        f"  Python: {platform.python_version()}\n"
        f"  Repository path: {repo_abs_path}\n"
        f"\n"
        f"PATH RULES:\n"
        f"  - ALL file operations MUST use absolute paths rooted at {repo_abs_path}\n"
        f"  - Example: '{repo_abs_path}{os.sep}src{os.sep}main.py'\n"
        f"  - For bash commands: 'cd {repo_abs_path} && <command>'\n"
        f"\n"
        f"DISCOVERY RULES:\n"
        f"  - Do NOT assume what languages, tools, or frameworks exist\n"
        f"  - Use a2a_tool with agent_name='discovery' to discover everything\n"
        f"  - Use checkpoint_tool to read findings from previous tasks\n"
        f"  - Use checkpoint_tool to save your own findings for later tasks\n"
    )

    if system == "Windows":
        context += (
            f"\n"
            f"WINDOWS NOTES:\n"
            f"  - bash_execution_tool uses PowerShell (with CMD fallback for &&)\n"
            f"  - Use ; for PowerShell chaining, && triggers CMD fallback\n"
            f"  - Avoid Unix-only commands (find, grep, sed, head, tail)\n"
            f"  - Use: Get-ChildItem, Select-String, Get-Content instead\n"
        )
    elif system == "Darwin":
        context += (
            f"\n"
            f"MACOS NOTES:\n"
            f"  - BSD sed: use 'sed -i \"\"' not 'sed -i'\n"
            f"  - Use 'brew install' for system packages if needed\n"
        )

    return context


# ── A2A Server Management ─────────────────────────────────

def _start_a2a_server(workspace_dir: str, port: int = 5000):
    """Start the A2A agent server in a background thread."""
    try:
        import uvicorn  # noqa
    except ImportError:
        logger.warning(
            "uvicorn not installed. A2A server disabled. "
            "Install with: pip install uvicorn fastapi httpx"
        )
        return

    try:
        from a2a.runner import main as run_a2a
    except ImportError:
        logger.warning(
            "a2a package not found. A2A server disabled. "
            "Create the a2a/ package or use --no_a2a flag."
        )
        return

    try:
        # If we get here, both dependencies exist
        from a2a.agents.discovery_agent import DiscoveryAgent, create_discovery_agent_card
        from a2a.agents.test_runner_agent import TestRunnerAgent, create_test_runner_agent_card
        from a2a.agents.fixer_agent import FixerAgent, create_fixer_agent_card
        from a2a.agents.linter_agent import LinterAgent, create_linter_agent_card
        from a2a.server import A2AAgentServer, create_a2a_app

        repo_dir = os.path.join(workspace_dir, "repo")
        base_url = f"http://localhost:{port}"

        agents = {
            "discovery": A2AAgentServer(
                create_discovery_agent_card(base_url),
                DiscoveryAgent().handle_task,
            ),
            "test-runner": A2AAgentServer(
                create_test_runner_agent_card(base_url),
                TestRunnerAgent(repo_dir).handle_task,
            ),
            "fixer": A2AAgentServer(
                create_fixer_agent_card(base_url),
                FixerAgent(repo_dir).handle_task,
            ),
            "linter": A2AAgentServer(
                create_linter_agent_card(base_url),
                LinterAgent(repo_dir).handle_task,
            ),
        }

        app = create_a2a_app(agents)
        uvicorn.run(app, host="localhost", port=port, log_level="warning")

    except Exception as e:
        logger.error(f"A2A server failed: {e}")


def _wait_for_a2a_server(port: int, timeout: int = 15) -> bool:
    """Wait for A2A server to become ready."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — skipping A2A server check")
        return False

    print("  Starting A2A agent server...", end="", flush=True)
    start = time.time()

    while time.time() - start < timeout:
        try:
            resp = httpx.get(
                f"http://localhost:{port}/.well-known/agent.json",
                timeout=2,
            )
            if resp.status_code == 200:
                data = resp.json()
                agent_count = len(data.get("agents", {}))
                agent_names = list(data.get("agents", {}).keys())
                print(f" [\033[92m✓\033[0m] {agent_count} agents: {', '.join(agent_names)}")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(0.5)

    print(" [\033[93m!\033[0m] Server not ready — pipeline will work without A2A")
    return False


# ── GitHub Authentication ─────────────────────────────────

def _authenticate_github() -> str:
    """Handle GitHub authentication."""
    existing = os.environ.get("GITHUB_AUTH_TKN")
    if existing:
        print("  [\033[92m✓\033[0m] GitHub: using GITHUB_AUTH_TKN from environment")
        return existing

    if not sys.stdin.isatty():
        print("  [\033[91m✗\033[0m] GITHUB_AUTH_TKN not set and running non-interactively")
        sys.exit(1)

    print("\n  --- GitHub Authentication ---")
    from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.github_oauth_tool import GitHubOAuthTool
    token = GitHubOAuthTool().get_or_request_token_interactive()
    if not token:
        print("  [\033[91m✗\033[0m] Authentication failed")
        sys.exit(1)
    return token


# ── Workspace Cleanup ─────────────────────────────────────

def _prepare_workspace(workspace_dir: str):
    """Clean up stale artifacts from previous runs."""
    import shutil

    meta_dir = os.path.join(workspace_dir, ".pipeline_meta")

    # Clear checkpoints (stale state from previous runs)
    checkpoints = os.path.join(meta_dir, "checkpoints")
    if os.path.exists(checkpoints):
        shutil.rmtree(checkpoints, ignore_errors=True)
        logger.info("Cleared stale checkpoints")

    # Clear coverage artifacts
    coverage = os.path.join(meta_dir, "coverage")
    if os.path.exists(coverage):
        shutil.rmtree(coverage, ignore_errors=True)

    # Clear old backups (keep most recent)
    if os.path.exists(workspace_dir):
        backups = sorted([
            d for d in os.listdir(workspace_dir)
            if d.startswith("repo_backup_")
        ])
        for old_backup in backups[:-1]:  # Keep latest
            bp = os.path.join(workspace_dir, old_backup)
            shutil.rmtree(bp, ignore_errors=True)
            logger.info(f"Removed old backup: {old_backup}")

    # Ensure directories exist
    os.makedirs(os.path.join(meta_dir, "checkpoints"), exist_ok=True)
    os.makedirs(os.path.join(meta_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(meta_dir, "coverage"), exist_ok=True)
    os.makedirs(os.path.join(meta_dir, "backups"), exist_ok=True)


# ── Default Inputs (for train/test/replay) ────────────────

def _default_inputs() -> dict:
    from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR
    return {
        'github_repo_url': 'https://github.com/test-org/sample-repo',
        'requirements': 'Add unit tests for core modules',
        'branch_name': 'feature/test-run',
        'default_branch': 'main',
        'timestamp': datetime.now().strftime("%Y%m%d-%H%M%S"),
        'env_context': _build_env_context(REPO_DIR),
        'repo_abs_path': REPO_DIR,
        'max_fix_iterations': 5,
    }


# ── Commands ──────────────────────────────────────────────

def run():
    """Run the full QA pipeline."""

    # Windows UTF-8
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
        REPO_DIR, WORKSPACE_DIR, MAX_FIX_ITERATIONS
    )
    from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import (
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew
    )

    # ── Parse CLI args ────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Run the Iterative QA Pipeline"
    )
    parser.add_argument("--repo_url", type=str, help="GitHub repository URL")
    parser.add_argument("--requirements", type=str, help="What should agents do?")
    parser.add_argument("--branch_name", type=str, default=None)
    parser.add_argument("--default_branch", type=str, default="main")
    parser.add_argument("--a2a_port", type=int, default=5000)
    parser.add_argument("--no_a2a", action="store_true", help="Skip A2A server")
    args = parser.parse_args(sys.argv[2:])

    # Interactive prompts if not provided
    if not args.repo_url:
        args.repo_url = input("GitHub repository URL: ").strip()
    if not args.requirements:
        args.requirements = input("What should the agents do? ").strip()

    args.repo_url = validate_github_url(args.repo_url)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if not args.branch_name:
        args.branch_name = f"feature/agent-update-{timestamp}"

    # ── Setup ─────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("ITERATIVE QA PIPELINE")
    print(f"{'=' * 60}")
    print(f"  Repo:      {args.repo_url}")
    print(f"  Branch:    {args.branch_name}")
    print(f"  Workspace: {REPO_DIR}")
    print()

    # Authenticate GitHub
    github_tkn = _authenticate_github()
    os.environ["GITHUB_AUTH_TKN"] = github_tkn

    # Prepare workspace
    _prepare_workspace(WORKSPACE_DIR)

    # Start A2A server
    a2a_available = False
    if not args.no_a2a:
        a2a_thread = threading.Thread(
            target=_start_a2a_server,
            args=(WORKSPACE_DIR, args.a2a_port),
            daemon=True,
        )
        a2a_thread.start()
        a2a_available = _wait_for_a2a_server(args.a2a_port)
        os.environ["A2A_BASE_URL"] = f"http://localhost:{args.a2a_port}"
    else:
        print("  A2A server: skipped (--no_a2a)")

    # ── Build inputs ──────────────────────────────────────
    inputs = {
        "github_repo_url": args.repo_url,
        "requirements": args.requirements,
        "branch_name": args.branch_name,
        "default_branch": args.default_branch,
        "timestamp": timestamp,
        "env_context": _build_env_context(REPO_DIR),
        "repo_abs_path": REPO_DIR,
        "max_fix_iterations": MAX_FIX_ITERATIONS,
        "a2a_available": str(a2a_available).lower(),
    }

    print(f"\n  Starting pipeline...")
    print()

    # ── Run pipeline ──────────────────────────────────────
    pipeline = IterativeQualityAssurancePipelineWithTestFixLoopsCrew()

    try:
        result = pipeline.crew().kickoff(inputs=inputs)

        print(f"\n{'=' * 60}")
        print("PIPELINE COMPLETED")
        print(f"{'=' * 60}")

        # Save result
        os.makedirs(os.path.dirname(REPO_DIR), exist_ok=True)
        output_path = os.path.join(
            os.path.dirname(REPO_DIR), "pipeline_result.md"
        )
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(result))
        print(f"  Result: {output_path}")

    except KeyboardInterrupt:
        print("\n  [!] Interrupted by user.")
        sys.exit(130)

    except Exception as e:
        import traceback
        print(f"\n  [\033[91m✗\033[0m] Pipeline failed: {e}")

        error_path = os.path.join(
            os.path.dirname(REPO_DIR), "pipeline_error.log"
        )
        os.makedirs(os.path.dirname(error_path), exist_ok=True)
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"Failed: {datetime.now().isoformat()}\n")
            f.write(f"Inputs: {inputs}\n\n")
            traceback.print_exc(file=f)
        print(f"  Error log: {error_path}")
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
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().replay(
            task_id=task_id
        )
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
            n_iterations=n_iterations,
            openai_model_name=model_name,
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"Test failed: {e}")



# ── Entry point ───────────────────────────────────────────

if __name__ == "__main__":
    commands = {"run": run, "train": train, "replay": replay, "test": test}

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: main.py <{'|'.join(commands)}> [args]")
        print()
        print("Commands:")
        print("  run     Run the full QA pipeline")
        print("  train   Train the crew for N iterations")
        print("  replay  Replay from a specific task")
        print("  test    Test crew execution")
        print()
        print("Run options:")
        print("  --repo_url URL       GitHub repository URL")
        print("  --requirements TEXT   What agents should do")
        print("  --branch_name NAME   Branch name (auto-generated if omitted)")
        print("  --default_branch     Default branch (default: main)")
        print("  --a2a_port PORT      A2A server port (default: 5000)")
        print("  --no_a2a             Skip A2A discovery server")
        sys.exit(1)

    commands[sys.argv[1]]()