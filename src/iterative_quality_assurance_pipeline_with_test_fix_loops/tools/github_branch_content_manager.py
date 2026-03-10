from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional
import requests
import json
import re
import base64
from datetime import datetime
import subprocess
import os
import time
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, HTTP_REQUEST_TIMEOUT
)


class GitHubOperationInput(BaseModel):
    """Input schema for GitHub Branch and Content Manager Tool."""
    operation: str = Field(..., description="Operation: 'get_repo_info', 'create_branch', 'get_file', 'clone_repo', 'commit_and_push', 'create_pr'")
    repository_url: str = Field(..., description="GitHub repository URL (e.g., 'https://github.com/owner/repo')")
    branch_name: Optional[str] = Field(default=None, description="Exact branch name to create or operate on")
    branch_name_prefix: Optional[str] = Field(default="feature", description="Prefix for auto-generated branch name (only if branch_name not provided)")
    file_path: Optional[str] = Field(default=None, description="Path to file in repository")
    commit_message: Optional[str] = Field(default=None, description="Commit message")
    pr_title: Optional[str] = Field(default=None, description="Pull request title")
    pr_description: Optional[str] = Field(default=None, description="Pull request description")
    source_branch: Optional[str] = Field(default=None, description="Source branch for operations")
    target_branch: Optional[str] = Field(default=None, description="Target branch (default: repo default)")
    workspace_dir: Optional[str] = Field(default=None, description="Local workspace directory (ignored, uses config)")


class GitHubBranchContentManager(BaseTool):
    """Tool for managing GitHub repository branches, cloning, pushing, and PRs."""

    name: str = "github_branch_content_manager"
    description: str = (
        "Manages GitHub operations: get_repo_info, create_branch, get_file, "
        "clone_repo, commit_and_push, create_pr. Always uses the configured "
        "repository directory for local operations."
    )
    args_schema: Type[BaseModel] = GitHubOperationInput

    def _sanitize_output(self, text: str, token: str) -> str:
        """Remove tokens from output strings."""
        if token:
            return text.replace(token, "***TOKEN***")
        return text

    def _parse_repository_url(self, url: str) -> Optional[tuple]:
        url = url.strip().rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        match = re.match(r'https://github\.com/([^/]+)/([^/]+)$', url)
        if match:
            return (match.group(1), match.group(2))
        return None

    def _github_request(self, method: str, url: str, headers: dict,
                        json_data: dict = None, max_retries: int = 3):
        """Make a GitHub API request with rate limit handling."""
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = requests.get(url, headers=headers, timeout=HTTP_REQUEST_TIMEOUT)
                else:
                    response = requests.post(url, headers=headers, json=json_data, timeout=HTTP_REQUEST_TIMEOUT)

                if response.status_code in (403, 429):
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if attempt < max_retries - 1:
                        time.sleep(min(retry_after, 120))
                        continue
                return response
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise
        return response

    def _run(self, operation: str, repository_url: str,
             branch_name: Optional[str] = None,
             branch_name_prefix: str = "feature",
             file_path: Optional[str] = None,
             commit_message: Optional[str] = None,
             pr_title: Optional[str] = None,
             pr_description: Optional[str] = None,
             source_branch: Optional[str] = None,
             target_branch: Optional[str] = None,
             workspace_dir: str = None) -> str:
        try:
            repo_parts = self._parse_repository_url(repository_url)
            if not repo_parts:
                return json.dumps({"success": False, "error": "Invalid URL. Expected: https://github.com/owner/repo"})

            owner, repo = repo_parts
            github_token = os.getenv('GITHUB_AUTH_TKN')
            if not github_token:
                return json.dumps({"success": False, "error": "GITHUB_AUTH_TKN not set."})

            headers = {
                'Authorization': f'token {github_token}',
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            }

            if operation == "get_repo_info":
                return self._get_repository_info(owner, repo, headers)
            elif operation == "create_branch":
                return self._create_branch(owner, repo, headers, branch_name, branch_name_prefix)
            elif operation == "get_file":
                if not file_path:
                    return json.dumps({"success": False, "error": "file_path required"})
                return self._get_file_content(owner, repo, headers, file_path, source_branch)
            elif operation == "clone_repo":
                return self._clone_repository(owner, repo, github_token, source_branch or "main")
            elif operation == "commit_and_push":
                if not source_branch:
                    return json.dumps({"success": False, "error": "source_branch required"})
                if not commit_message:
                    return json.dumps({"success": False, "error": "commit_message required"})
                return self._commit_and_push(commit_message, source_branch, github_token)
            elif operation == "create_pr":
                if not source_branch:
                    return json.dumps({"success": False, "error": "source_branch required"})
                return self._create_pull_request(owner, repo, headers, source_branch, target_branch, pr_title, pr_description)
            else:
                return json.dumps({"success": False, "error": f"Unknown operation: {operation}"})

        except Exception as e:
            return json.dumps({"success": False, "error": f"Unexpected error: {str(e)}"})

    def _get_repository_info(self, owner, repo, headers):
        try:
            response = self._github_request("GET", f"https://api.github.com/repos/{owner}/{repo}", headers)
            if response.status_code == 200:
                data = response.json()
                return json.dumps({
                    "success": True,
                    "repository_info": {
                        "name": data.get("name"),
                        "full_name": data.get("full_name"),
                        "default_branch": data.get("default_branch"),
                        "private": data.get("private"),
                        "clone_url": data.get("clone_url")
                    }
                }, indent=2)
            return json.dumps({"success": False, "error": f"Failed. Status: {response.status_code}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def _create_branch(self, owner, repo, headers, branch_name=None, branch_prefix="feature"):
        try:
            repo_info = self._github_request("GET", f"https://api.github.com/repos/{owner}/{repo}", headers)
            if repo_info.status_code != 200:
                return json.dumps({"success": False, "error": "Failed to get repo info"})

            default_branch = repo_info.json().get("default_branch", "main")
            ref_resp = self._github_request("GET",
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{default_branch}", headers)
            if ref_resp.status_code != 200:
                return json.dumps({"success": False, "error": "Failed to get default branch ref"})

            default_sha = ref_resp.json()["object"]["sha"]

            # Use exact branch name if provided, otherwise generate one
            if not branch_name:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                branch_name = f"{branch_prefix}-{timestamp}"

            # Check if branch already exists
            check_resp = self._github_request("GET",
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch_name}", headers)
            if check_resp.status_code == 200:
                return json.dumps({
                    "success": True,
                    "branch_created": {
                        "branch_name": branch_name,
                        "source_branch": default_branch,
                        "already_existed": True
                    }
                }, indent=2)

            create_data = {"ref": f"refs/heads/{branch_name}", "sha": default_sha}
            create_resp = self._github_request("POST",
                f"https://api.github.com/repos/{owner}/{repo}/git/refs", headers, create_data)

            if create_resp.status_code == 201:
                return json.dumps({
                    "success": True,
                    "branch_created": {
                        "branch_name": branch_name,
                        "source_branch": default_branch,
                        "source_sha": default_sha,
                        "already_existed": False
                    }
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": f"Failed to create branch. Status: {create_resp.status_code}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def _get_file_content(self, owner, repo, headers, file_path, branch=None):
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
            if branch:
                url += f"?ref={branch}"
            response = self._github_request("GET", url, headers)
            if response.status_code == 200:
                data = response.json()
                content = ""
                if data.get("encoding") == "base64":
                    content = base64.b64decode(data["content"]).decode('utf-8')
                else:
                    content = data.get("content", "")
                return json.dumps({
                    "success": True,
                    "file_info": {"path": data.get("path"), "content": content}
                }, indent=2)
            return json.dumps({"success": False, "error": f"Failed. Status: {response.status_code}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def _clone_repository(self, owner, repo, token, branch):
        try:
            target_dir = REPO_DIR
            # Use credential helper approach to keep token out of URLs/logs
            clean_url = f"https://github.com/{owner}/{repo}.git"

            env = os.environ.copy()
            # Pass credentials via git header (keeps token out of remote URL)
            encoded_cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
            env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {encoded_cred}"
            env["GIT_TERMINAL_PROMPT"] = "0"

            if os.path.exists(target_dir) and os.path.isdir(os.path.join(target_dir, ".git")):
                # Update existing clone
                cmds = [
                    ["git", "fetch", "origin"],
                    ["git", "checkout", branch],
                    ["git", "pull", "origin", branch]
                ]
                outputs = []
                for cmd in cmds:
                    res = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True, env=env, timeout=120)
                    outputs.append(f"Command: {' '.join(cmd)}\nOutput: {res.stdout}\nError: {res.stderr}")
                    if res.returncode != 0:
                        return json.dumps({
                            "success": False,
                            "error": f"Failed: {' '.join(cmd)}",
                            "logs": outputs
                        })
                return json.dumps({
                    "success": True,
                    "message": f"Updated branch {branch} in {target_dir}",
                    "absolute_path": target_dir
                })

            # Fresh clone
            if os.path.exists(target_dir):
                # Back up existing non-git content instead of destroying
                import shutil
                backup = f"{target_dir}_backup_{datetime.now().strftime('%H%M%S')}"
                contents = os.listdir(target_dir) if os.path.isdir(target_dir) else []
                if contents:
                    shutil.move(target_dir, backup)
                else:
                    shutil.rmtree(target_dir, ignore_errors=True)

            os.makedirs(os.path.dirname(target_dir), exist_ok=True)
            result = subprocess.run(
                ["git", "clone", "-b", branch, clean_url, target_dir],
                capture_output=True, text=True, env=env, timeout=300
            )

            if result.returncode == 0:
                return json.dumps({
                    "success": True,
                    "message": f"Cloned branch {branch} into {target_dir}",
                    "absolute_path": target_dir
                })
            else:
                sanitized_err = self._sanitize_output(result.stderr, token)
                return json.dumps({"success": False, "error": f"Clone failed: {sanitized_err}"})
        except subprocess.TimeoutExpired:
            return json.dumps({"success": False, "error": "Clone timed out after 300 seconds."})
        except Exception as e:
            return json.dumps({"success": False, "error": self._sanitize_output(str(e), token)})

    def _commit_and_push(self, commit_message, branch, token):
        try:
            repo_dir = REPO_DIR
            if not os.path.exists(repo_dir):
                return json.dumps({"success": False, "error": f"Repository not found at {repo_dir}"})

            env = os.environ.copy()
            encoded_cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
            env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {encoded_cred}"
            env["GIT_TERMINAL_PROMPT"] = "0"

            cmds = [
                (["git", "config", "user.name", "CrewAI Agent"], False),
                (["git", "config", "user.email", "crewai@agent.local"], False),
                (["git", "add", "."], True),
                (["git", "commit", "-m", commit_message], False),
                (["git", "push", "origin", branch], True),
            ]

            outputs = []
            for cmd, is_critical in cmds:
                res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, env=env, timeout=120)
                combined = res.stdout + res.stderr
                outputs.append(self._sanitize_output(combined, token))

                if res.returncode != 0:
                    # Non-critical failures we can skip
                    if "nothing to commit" in combined:
                        continue
                    if cmd[1] == "config":
                        continue
                    if is_critical:
                        return json.dumps({
                            "success": False,
                            "error": f"Failed: {' '.join(cmd[:3])}",
                            "output": self._sanitize_output(combined, token),
                            "logs": outputs
                        })

            return json.dumps({
                "success": True,
                "message": "Successfully committed and pushed changes.",
                "logs": outputs
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"success": False, "error": "Git operation timed out."})
        except Exception as e:
            return json.dumps({"success": False, "error": self._sanitize_output(str(e), token)})

    def _create_pull_request(self, owner, repo, headers, source_branch,
                             target_branch=None, title=None, description=None):
        try:
            if not target_branch:
                repo_resp = self._github_request("GET", f"https://api.github.com/repos/{owner}/{repo}", headers)
                target_branch = repo_resp.json().get("default_branch", "main") if repo_resp.status_code == 200 else "main"

            # Validate branches
            source_resp = self._github_request("GET",
                f"https://api.github.com/repos/{owner}/{repo}/branches/{source_branch}", headers)
            if source_resp.status_code != 200:
                return json.dumps({"success": False, "error": f"Source branch '{source_branch}' not found on remote."})

            target_resp = self._github_request("GET",
                f"https://api.github.com/repos/{owner}/{repo}/branches/{target_branch}", headers)
            if target_resp.status_code != 200:
                return json.dumps({"success": False, "error": f"Target branch '{target_branch}' not found on remote."})

            data = {
                "title": title or f"Pull request from {source_branch}",
                "head": source_branch,
                "base": target_branch,
                "body": description or f"Automated PR from {source_branch} to {target_branch}"
            }

            response = self._github_request("POST",
                f"https://api.github.com/repos/{owner}/{repo}/pulls", headers, data)
            if response.status_code == 201:
                pr_data = response.json()
                return json.dumps({
                    "success": True,
                    "pull_request": {
                        "number": pr_data.get("number"),
                        "html_url": pr_data.get("html_url")
                    }
                })
            else:
                return json.dumps({
                    "success": False,
                    "error": f"PR creation failed. Status: {response.status_code}. Response: {response.text[:500]}"
                })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})