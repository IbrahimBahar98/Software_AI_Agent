import os

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
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.checkpoint_tool import CheckpointTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.test_coverage_tool import TestCoverageTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.ci_config_reader_tool import CIConfigReaderTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools.mcp_bridge_tool import MCPBridgeTool
from iterative_quality_assurance_pipeline_with_test_fix_loops.run_logger import RunLogger

from iterative_quality_assurance_pipeline_with_test_fix_loops.config import MODEL_HEAVY, MODEL_LIGHT, DASHSCOPE_BASE_URL

api_key = os.getenv("DASHSCOPE_API_KEY")
if not api_key:
    import warnings
    warnings.warn("DASHSCOPE_API_KEY not found in environment. Using fallback. Please add it to .env")
    api_key = "sk-099f1a284aef4f3eb9c759bc578e7603"

# Alibaba Cloud Model Studio — Qwen-Plus (via DashScope OpenAI-compatible API)
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

    @agent
    def repository_analyst_and_task_planner(self) -> Agent:
        return Agent(
            config=self.agents_config["repository_analyst_and_task_planner"],
            tools=[
                FileReadTool(),
				GitHubRepositoryInspector(),
				GitHubBranchContentManager(),
                MCPBridgeTool() # For GitHub MCP & Sequential Thinking
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=20,
            max_rpm=None,
            max_execution_time=600,
            llm=local_llm
        )
    
    @agent
    def software_developer(self) -> Agent:
        return Agent(
            config=self.agents_config["software_developer"],
            tools=[
                FileReadTool(),
				GitHubRepositoryInspector(),
				BashExecutionTool(),
				FileWriteTool(),
                MCPBridgeTool() # For Sequential Thinking
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            apps=["github/get_file"],
            max_execution_time=600,
            llm=local_llm
        )
    
    @agent
    def test_strategy_designer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_strategy_designer"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                CIConfigReaderTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            max_execution_time=600,
            llm=local_llm
        )
    
    @agent
    def test_implementation_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_implementation_engineer"],
            tools=[
                FileReadTool(),
				BashExecutionTool(),
				FileWriteTool()  # Clean test file creation
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            max_execution_time=600,
            llm=local_llm
        )
    
    @agent
    def test_execution_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["test_execution_specialist"],
            tools=[
                FileReadTool(),
                BashExecutionTool(),
                LintGateTool(),
                TestCoverageTool(),
                MCPBridgeTool() # For Puppeteer UI Verification
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            max_execution_time=600,
            llm=local_llm
        )
    
    @agent
    def qa_report_generator(self) -> Agent:
        return Agent(
            config=self.agents_config["qa_report_generator"],
            tools=[FileReadTool()],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=10,
            max_rpm=None,
            max_execution_time=600,
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
                FileReadTool()
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=15,
            max_rpm=None,
            apps=[
                "github/create_issue",
                "github/create_release",
                "github/get_file"
            ],
            max_execution_time=600,
            llm=light_llm
        )
    
    @agent
    def iterative_test_and_fix_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["iterative_test_and_fix_specialist"],
            tools=[
                FileReadTool(),
				GitHubRepositoryInspector(),
                BashExecutionTool(),
				PatchApplyTool(),
                MCPBridgeTool() # For Sequential Thinking
            ],
            verbose=True,
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=40,
            max_rpm=None,
            max_execution_time=600,
            llm=local_llm
        )
    

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
    def lint_gate_task(self) -> Task:
        return Task(
            config=self.tasks_config["lint_gate_task"],
            markdown=False
        )
    
    @task
    def execute_tests_and_analyze_results(self) -> Task:
        return Task(
            config=self.tasks_config["execute_tests_and_analyze_results"],
            markdown=False
        )
    
    @task
    def generate_final_quality_assurance_report(self) -> Task:
        return Task(
            config=self.tasks_config["generate_final_quality_assurance_report"],
            markdown=False
        )
    
    @task
    def execute_iterative_test_fix_loop(self) -> Task:
        return Task(
            config=self.tasks_config["execute_iterative_test_fix_loop"],
            markdown=False
        )
    
    @task
    def create_github_issues_and_track_progress(self) -> Task:
        return Task(
            config=self.tasks_config["create_github_issues_and_track_progress"],
            markdown=False
        )
    

    @crew
    def crew(self) -> Crew:
        """Creates the IterativeQualityAssurancePipelineWithTestFixLoops crew"""
        logger = RunLogger()
        cr = Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            function_calling_llm=local_llm,
            task_callback=logger.task_callback,
            step_callback=logger.step_callback
        )
        return cr
