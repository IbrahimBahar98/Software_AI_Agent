# Setup and Execution Instructions

Follow these steps to configure and run the Iterative Quality Assurance Pipeline.

## 1. Prerequisites
- Python 3.10 to 3.13
- Git installed on your machine
- [uv](https://docs.astral.sh/uv/) installed (Python package manager used by CrewAI)
  - Install via pip: `pip install uv`

## 2. Environment Variables
The pipeline requires a model provider API key, configured via a `.env` file in the project root.

### A. Model Provider Key (Alibaba Cloud Model Studio)
The pipeline is currently configured to use `openai/qwen-plus` via the DashScope API. 
Create a `.env` file (copy from `.env.example`) and add your key:
```env
DASHSCOPE_API_KEY=sk-your_api_key_here
```

### B. GitHub Authentication (OAuth Redirect Flow - VS Code Style)
The pipeline uses a seamless, browser-based authentication flow. When you run the script, it will automatically open your default browser to GitHub to authorize the project.

**To set this up for your first run:**

1.  **Register a New OAuth App**:
    - Go to your [GitHub Settings](https://github.com/settings/developers) -> **Developer Settings** -> **OAuth Apps** -> **New OAuth App**.
    - **Application Name**: `QA Pipeline` (or any name).
    - **Homepage URL**: `http://localhost:8080`.
    - **Authorization callback URL**: `http://localhost:8080` (⚠️ **CRITICAL**: Must match this exactly).
    - Click **Register application**.
2.  **Generate Credentials**:
    - Copy your **Client ID**.
    - Click **"Generate a new client secret"** and copy that secret safely.
3.  **Update `.env`**:
    - Add these lines to your `.env` file:
    ```env
    GITHUB_OAUTH_CLIENT_ID=your_client_id_here
    GITHUB_CLIENT_SECRET=your_client_secret_here
    ```

## 3. Running the Pipeline

Kick off the process using `uv`:

```bash
python -m uv run iterative_quality_assurance_pipeline_with_test_fix_loops run --repo_url "https://github.com/user/repo" --requirements "your info"
```

## 4. Authentication Flow
- The script will pause and open your browser automatically.
- Click the green **"Authorize"** button in your browser.
- The browser will show a **"Success!"** message.
- The script in the terminal will immediately resume execution.

## 5. What Happens Next?
- A `./workspace` folder will appear in the directory. **Do not modify this folder manually while the agents are running**.
- You will see the agents discussing and working in the terminal. The process can take anywhere from 5 to 25 minutes depending on the complexity of your requirements.
- Once finished, a new Pull Request will be waiting for you to review on GitHub!

## 6. MCP Integration (Automatic)
The pipeline now uses **Model Context Protocol (MCP)** servers to give agents extra powers:
- **GitHub**: Advanced code search and issue tracking.
- **Puppeteer**: Automated browser testing for UI enhancements.
- **Sequential Thinking**: Structured reasoning for complex fixes.

**No Installation Required**: These servers run automatically via `npx -y`. As long as you have Node.js installed (verified at v22), the pipeline will fetch and run them in the background without requiring Administrator rights or Docker.

