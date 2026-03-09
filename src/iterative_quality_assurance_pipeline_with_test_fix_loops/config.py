import os

# Base Workspace Directory
WORKSPACE_DIR = os.path.abspath(os.getenv("WORKSPACE_DIR", "./workspace"))
# Repository Directory (Isolated from logs in WORKSPACE_DIR)
REPO_DIR = os.path.abspath(os.path.join(WORKSPACE_DIR, "repo"))

# Token Cache Directory for OAuth
TOKEN_CACHE_DIR = os.path.expanduser("~/.config/crewai-qa")

# GitHub OAuth App settings (Replace with your actual Client ID if deploying)
# A default Client ID for testing purposes (this is just an example, users will need their own)
GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "Iv23liBqUhwQ2xS0N4wY") 

# Iteration Caps
MAX_FIX_ITERATIONS = 5

# LLM Configurations
MODEL_HEAVY = "openai/qwen-plus"
MODEL_LIGHT = "openai/qwen-turbo"

# API Endpoints
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
