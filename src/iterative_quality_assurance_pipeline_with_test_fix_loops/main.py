#!/usr/bin/env python
import sys
import os
from datetime import datetime
import argparse
from iterative_quality_assurance_pipeline_with_test_fix_loops.crew import IterativeQualityAssurancePipelineWithTestFixLoopsCrew

# This main file is intended to be a way for your to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """Run the crew with optional CLI arguments."""
    # Force UTF-8 encoding for stdout/stderr to support emojis/checkmarks on Windows
    # chcp 65001 sets the code page to UTF-8
    if os.name == 'nt':
        os.system('chcp 65001 > nul')

    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass
            
    parser = argparse.ArgumentParser(description="Run the QA pipeline")
    parser.add_argument("--repo_url", type=str, help="GitHub repository URL")
    parser.add_argument("--requirements", type=str, help="Requirements for the agents")
    parser.add_argument("--branch_name", type=str, default=None, help="Feature branch name")
    parser.add_argument("--default_branch", type=str, default="main", help="Default branch name")
    # Skip the subcommand word (e.g. "run") so argparse only sees --flags
    args = parser.parse_args(sys.argv[2:])

    # Fallback to interactive prompts if arguments are missing
    if not args.repo_url:
        args.repo_url = input("Enter the GitHub repository URL to clone and modify (e.g., https://github.com/user/repo): ").strip()
    if not args.requirements:
        args.requirements = input("What do you want the agents to do to this repository? ").strip()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if not args.branch_name:
        args.branch_name = f"feature/agent-update-{timestamp}"

    # GitHub authentication via OAuth tool
    print("\n--- GitHub Authentication ---")
    from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.github_oauth_tool import GitHubOAuthTool
    oauth_tool = GitHubOAuthTool()
    github_tkn = oauth_tool.get_or_request_token_interactive()
    if github_tkn:
        os.environ["GITHUB_AUTH_TKN"] = github_tkn
    else:
        print("[\033[91mX\033[0m] Failed to authenticate. Exiting.")
        sys.exit(1)

    import platform
    os_name = platform.system()
    if os_name == "Windows":
        os_context = (
            "WORKSPACE CONTEXT: You are operating strictly on a Windows machine using PowerShell. "
            "CRITICAL: You MUST retrieve the ABSOLUTE repository path from the tool outputs at the start of your task. "
            "You MUST strictly prepend this absolute path to all filenames when reading, writing, or executing files. "
            "Example: If the repo is at 'C:\\Users\\...\\repo', always use 'C:\\Users\\...\\repo\\package.json'. "
            "Use backslashes (\\) for all paths."
        )
    else:
        os_context = (
            "WORKSPACE CONTEXT: You are operating on a Unix-like system (Linux/Mac) using Bash. "
            "Use standard POSIX commands (ls, cat, rm, etc.) and forward slashes (/) for paths."
        )

    inputs = {
        "github_repo_url": args.repo_url,
        "requirements": args.requirements,
        "branch_name": args.branch_name,
        "default_branch": args.default_branch,
        "timestamp": timestamp,
        "os_context": os_context,
    }

    print("\nStarting the CrewAI Pipeline...\n")
    IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        'github_repo_url': 'sample_value',
        'requirements': 'sample_value',
        'branch_name': 'sample_value',
        'default_branch': 'sample_value',
        'timestamp': 'sample_value'
    }
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        'github_repo_url': 'sample_value',
        'requirements': 'sample_value',
        'branch_name': 'sample_value',
        'default_branch': 'sample_value',
        'timestamp': 'sample_value'
    }
    try:
        IterativeQualityAssurancePipelineWithTestFixLoopsCrew().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: main.py <command> [<args>]")
        sys.exit(1)

    command = sys.argv[1]
    if command == "run":
        run()
    elif command == "train":
        train()
    elif command == "replay":
        replay()
    elif command == "test":
        test()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
