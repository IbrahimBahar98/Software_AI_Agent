# a2a/runner.py
"""Starts the A2A server hosting all pipeline agents."""

import argparse
import logging
import uvicorn
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Start A2A agent server")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument(
        "--workspace", type=str,
        default=os.environ.get("WORKSPACE_DIR", "./workspace"),
    )
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace)
    repo_dir = os.path.join(workspace, "repo")
    base_url = f"http://{args.host}:{args.port}"

    logger.info(f"Starting A2A server on {base_url}")
    logger.info(f"Workspace: {workspace}")
    logger.info(f"Repo dir: {repo_dir}")

    # Import all agents
    from .agents.discovery_agent import (
        DiscoveryAgent, create_discovery_agent_card,
    )
    from .agents.test_runner_agent import (
        TestRunnerAgent, create_test_runner_agent_card,
    )
    from .agents.fixer_agent import (
        FixerAgent, create_fixer_agent_card,
    )
    from .agents.linter_agent import (
        LinterAgent, create_linter_agent_card,
    )
    from .server import A2AAgentServer, create_a2a_app

    # Create agent instances
    discovery = DiscoveryAgent()
    test_runner = TestRunnerAgent(workspace_dir=repo_dir)
    fixer = FixerAgent(workspace_dir=repo_dir)
    linter = LinterAgent(workspace_dir=repo_dir)

    # Wrap in A2A servers
    agents = {
        "discovery": A2AAgentServer(
            create_discovery_agent_card(base_url),
            discovery.handle_task,
        ),
        "test-runner": A2AAgentServer(
            create_test_runner_agent_card(base_url),
            test_runner.handle_task,
        ),
        "fixer": A2AAgentServer(
            create_fixer_agent_card(base_url),
            fixer.handle_task,
        ),
        "linter": A2AAgentServer(
            create_linter_agent_card(base_url),
            linter.handle_task,
        ),
    }

    app = create_a2a_app(agents)

    logger.info(f"Registered agents: {list(agents.keys())}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()