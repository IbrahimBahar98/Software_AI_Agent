"""Central configuration for the Iterative QA Pipeline."""
import os

# ──────────────────────────────────────────────
# Workspace Paths (Single Source of Truth)
# ──────────────────────────────────────────────
WORKSPACE_DIR = os.path.abspath(os.getenv("WORKSPACE_DIR", "./workspace"))
REPO_DIR = os.path.abspath(os.path.join(WORKSPACE_DIR, "repo"))
CHECKPOINT_DIR = os.path.join(WORKSPACE_DIR, ".pipeline_meta", "checkpoints")
LOG_DIR = os.path.join(WORKSPACE_DIR, ".pipeline_meta", "logs")
COVERAGE_DIR = os.path.join(WORKSPACE_DIR, ".pipeline_meta", "coverage")

# ──────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────
TOKEN_CACHE_DIR = os.path.expanduser("~/.config/crewai-qa")

GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
if not GITHUB_OAUTH_CLIENT_ID:
    import warnings
    warnings.warn(
        "GITHUB_OAUTH_CLIENT_ID not set. OAuth flow will fail. "
        "Register at https://github.com/settings/developers",
        stacklevel=2
    )

# ──────────────────────────────────────────────
# LLM Configuration
# ──────────────────────────────────────────────
MODEL_HEAVY = "openai/qwen-plus"       # 128K context, 8K output
MODEL_LIGHT = "openai/qwen-turbo"      # 128K context, 8K output
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# ──────────────────────────────────────────────
# Agent Constraints
# ──────────────────────────────────────────────
MAX_FIX_ITERATIONS = 5
MAX_FIX_AGENT_TOOL_CALLS = 30          # 5 cycles × ~6 calls each

AGENT_TIMEOUT_DEFAULT = 600             # 10 min
AGENT_TIMEOUT_ANALYST = 900             # 15 min
AGENT_TIMEOUT_DEVELOPER = 900           # 15 min
AGENT_TIMEOUT_FIX_LOOP = 1800          # 30 min

# ──────────────────────────────────────────────
# Tool Constraints
# ──────────────────────────────────────────────
MAX_FILE_READ_LINES = 200
MAX_FILE_WRITE_BYTES = 500_000          # 500KB safety cap
MAX_BASH_TIMEOUT = 120                  # seconds per command
MAX_BASH_OUTPUT_CHARS = 50_000
MAX_LINT_OUTPUT_CHARS = 5_000
MAX_TEST_OUTPUT_CHARS = 10_000
MAX_FILE_CONTENT_CHARS = 30_000         # For GitHub API file reads
MAX_MCP_TIMEOUT = 30
HTTP_REQUEST_TIMEOUT = 30

# ──────────────────────────────────────────────
# Supported Languages & Ecosystems
# ──────────────────────────────────────────────
SUPPORTED_LANGUAGES = [
    "python", "javascript", "typescript", "java",
    "c", "cpp", "csharp", "go", "rust", "ruby", "php", "swift"
]