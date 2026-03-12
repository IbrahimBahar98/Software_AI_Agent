import os
import logging

from crewai import LLM
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.github_repository_inspector import GitHubRepositoryInspector
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.github_branch_content_manager import GitHubBranchContentManager
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.bash_execution_tool import BashExecutionTool
from crewai_tools import FileReadTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.file_write_tool import FileWriteTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.patch_apply_tool import PatchApplyTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.lint_gate_tool import LintGateTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.dependency_installer_tool import DependencyInstallerTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.checkpoint_tool import CheckpointTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.test_coverage_tool import TestCoverageTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.ci_config_reader_tool import CIConfigReaderTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.mcp_bridge_tool import MCPBridgeTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.run_logger import RunLogger
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.a2a_tool import A2ATool

from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    MODEL_HEAVY, MODEL_LIGHT, DASHSCOPE_BASE_URL,
    AGENT_TIMEOUT_DEFAULT, AGENT_TIMEOUT_ANALYST,
    AGENT_TIMEOUT_DEVELOPER, AGENT_TIMEOUT_FIX_LOOP,
    MAX_FIX_AGENT_TOOL_CALLS
)

logger = logging.getLogger(__name__)

# ── API Key ──────────────────────────────────────────────
api_key = os.getenv("DASHSCOPE_API_KEY")
if not api_key:
    raise EnvironmentError(
        "DASHSCOPE_API_KEY not set. "
        "Run: export DASHSCOPE_API_KEY='your-key' or add to .env"
    )

local_llm = LLM(
    model=MODEL_HEAVY,
    api_key=api_key,
    base_url=DASHSCOPE_BASE_URL
)

light_llm = LLM(
    model=MODEL_LIGHT,
    api_key=api_key,
    base_url=DASHSCOPE_BASE_URL
)


@CrewBase
class IterativeQualityAssurancePipelineWithTestFixLoopsCrew:
    """IterativeQualityAssurancePipelineWithTestFixLoops crew"""

    def __init__(self):
        self.logger = RunLogger()

    # ── AGENTS ────────────────────────────────────────────

    @agent
    def repository_analyst_and_task_planner(self) -> Agent:
        return Agent(
            config=self.agents_config["repository_analyst_and_task_planner"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                GitHubRepositoryInspector(),
                GitHubBranchContentManager(),
                CheckpointTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=True,
            max_reasoning_attempts=3,
            inject_date=True,
            allow_delegation=False,
            max_iter=20,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_ANALYST,
            llm=local_llm
        )

    @agent
    def software_developer(self) -> Agent:
        return Agent(
            config=self.agents_config["software_developer"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEVELOPER,
            llm=local_llm
        )

    @agent
    def test_strategy_designer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_strategy_designer"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                CIConfigReaderTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEFAULT,
            llm=local_llm
        )

    @agent
    def test_implementation_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_implementation_engineer"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),
                DependencyInstallerTool()    # Can install test frameworks
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEVELOPER,
            llm=local_llm
        )

    @agent
    def test_execution_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["test_execution_specialist"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),             # Can fix lint issues
                DependencyInstallerTool(),   # Installs linters + configs
                LintGateTool(),              # Runs linters
                TestCoverageTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEFAULT,
            llm=local_llm
        )

    @agent
    def qa_report_generator(self) -> Agent:
        return Agent(
            config=self.agents_config["qa_report_generator"],
            tools=[
                FileReadTool(),
                FileWriteTool(),
                CheckpointTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=10,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEFAULT,
            llm=light_llm
        )

    @agent
    def github_integration_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["github_integration_specialist"],
            tools=[
                GitHubRepositoryInspector(),
                GitHubBranchContentManager(),
                BashExecutionTool(),
                FileReadTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_DEFAULT,
            llm=light_llm
        )

    @agent
    def iterative_test_and_fix_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["iterative_test_and_fix_specialist"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),
                PatchApplyTool(),
                DependencyInstallerTool(),   # Can install missing deps during fix
                LintGateTool(),              # Can re-lint after fixes
                TestCoverageTool(),
                CheckpointTool(),
                MCPBridgeTool()
            ],
            verbose=True,
            reasoning=True,
            max_reasoning_attempts=3,
            inject_date=True,
            allow_delegation=False,
            max_iter=MAX_FIX_AGENT_TOOL_CALLS,
            max_rpm=None,
            max_execution_time=AGENT_TIMEOUT_FIX_LOOP,
            llm=local_llm
        )
        
    @agent
    def repository_analyst_and_task_planner(self) -> Agent:
        return Agent(
            config=self.agents_config["repository_analyst_and_task_planner"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                GitHubRepositoryInspector(),
                GitHubBranchContentManager(),
                CheckpointTool(),
                A2ATool(),          # REPLACES MCPBridgeTool for discovery
            ],
            verbose=True,
            reasoning=True,
            max_reasoning_attempts=3,
            inject_date=True,
            allow_delegation=False,
            max_iter=20,
            max_execution_time=AGENT_TIMEOUT_ANALYST,
            llm=local_llm,
        )
    
    @agent
    def test_execution_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["test_execution_specialist"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),
                A2ATool(),           # For test-runner and discovery agents
                CheckpointTool(),
            ],
            verbose=True,
            max_iter=15,
            max_execution_time=AGENT_TIMEOUT_DEFAULT,
            llm=local_llm,
        )
    
    @agent
    def iterative_test_and_fix_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["iterative_test_and_fix_specialist"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                FileWriteTool(),
                PatchApplyTool(),
                A2ATool(),            # For test-runner + fixer agents
                CheckpointTool(),
            ],
            verbose=True,
            reasoning=True,
            max_reasoning_attempts=3,
            max_iter=MAX_FIX_AGENT_TOOL_CALLS,
            max_execution_time=AGENT_TIMEOUT_FIX_LOOP,
            llm=local_llm,
        )

    # ── TASKS ─────────────────────────────────────────────

    @task
    def analyze_github_repository_and_create_development_plan(self) -> Task:
        return Task(
            config=self.tasks_config["analyze_github_repository_and_create_development_plan"],
            markdown=False
        )

    @task
    def implement_code_based_on_development_plan(self) -> Task:
        return Task(
            config=self.tasks_config["implement_code_based_on_development_plan"],
            markdown=False
        )

    @task
    def design_comprehensive_testing_strategy(self) -> Task:
        return Task(
            config=self.tasks_config["design_comprehensive_testing_strategy"],
            markdown=False
        )

    @task
    def implement_automated_test_suite(self) -> Task:
        return Task(
            config=self.tasks_config["implement_automated_test_suite"],
            markdown=False
        )

    @task
    def execute_lint_and_tests(self) -> Task:
        """Was: lint_gate_task + execute_tests_and_analyze_results (now merged)."""
        return Task(
            config=self.tasks_config["execute_lint_and_tests"],
            markdown=False
        )

    @task
    def execute_iterative_test_fix_loop(self) -> Task:
        return Task(
            config=self.tasks_config["execute_iterative_test_fix_loop"],
            markdown=False
        )

    @task
    def generate_final_quality_assurance_report(self) -> Task:
        return Task(
            config=self.tasks_config["generate_final_quality_assurance_report"],
            markdown=False
        )

    @task
    def create_github_issues_and_track_progress(self) -> Task:
        return Task(
            config=self.tasks_config["create_github_issues_and_track_progress"],
            markdown=False
        )

    # ── CREW ──────────────────────────────────────────────

    @crew
    def crew(self) -> Crew:
        """Creates the crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            function_calling_llm=local_llm,
            task_callback=self.logger.task_callback,
            step_callback=self.logger.step_callback,
        )