from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Dict, Any, Optional
import requests
import json
import base64
from datetime import datetime
import subprocess
import os
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import REPO_DIR

class GitHubOperationInput(BaseModel):
    """Input schema for GitHub Branch and Content Manager Tool."""
    operation: str = Field(..., description="The operation to perform: 'get_repo_info', 'create_branch', 'get_file', 'clone_repo', 'commit_and_push', 'create_pr'")
    repository_url: str = Field(..., description="GitHub repository URL (e.g., 'https://github.com/owner/repo')")
    branch_name_prefix: Optional[str] = Field(default="feature", description="Prefix for new branch name (default: 'feature')")
    file_path: Optional[str] = Field(default=None, description="Path to file in repository (required for get_file)")
    commit_message: Optional[str] = Field(default=None, description="Commit message for commit_and_push")
    pr_title: Optional[str] = Field(default=None, description="Pull request title")
    pr_description: Optional[str] = Field(default=None, description="Pull request description")
    source_branch: Optional[str] = Field(default=None, description="Source branch for pull request")
    target_branch: Optional[str] = Field(default=None, description="Target branch for pull request (default: repository default branch)")
    workspace_dir: Optional[str] = Field(default="./workspace", description="Local workspace directory for cloning")

class GitHubBranchContentManager(BaseTool):
    """Tool for managing GitHub repository branches, cloning to local workspace, and pushing changes."""

    name: str = "github_branch_content_manager"
    description: str = (
        "Manages GitHub repository operations including: getting repository info, "
        "creating branches from default branch, fetching files, cloning repositories "
        "to a local workspace, committing/pushing changes from local workspace, "
        "and creating pull requests."
    )
    args_schema: Type[BaseModel] = GitHubOperationInput

    def _run(
        self, 
        operation: str,
        repository_url: str,
        branch_name_prefix: str = "feature",
        file_path: Optional[str] = None,
        commit_message: Optional[str] = None,
        pr_title: Optional[str] = None,
        pr_description: Optional[str] = None,
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        workspace_dir: str = "./workspace"
    ) -> str:
        """Execute GitHub operations via REST API or local git commands."""
        
        try:
            # Parse repository URL to extract owner and repo
            repo_parts = self._parse_repository_url(repository_url)
            if not repo_parts:
                return json.dumps({"success": False, "error": "Invalid repository URL format. Expected: https://github.com/owner/repo"})
            
            owner, repo = repo_parts
            
            # Get GitHub token from environment
            github_token = os.getenv('GITHUB_AUTH_TKN')
            if not github_token:
                return json.dumps({"success": False, "error": "GitHub token not found. Set GITHUB_AUTH_TKN environment variable."})
            
            headers = {
                'Authorization': f'token {github_token}',
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            }
            
            # Execute requested operation
            if operation == "get_repo_info":
                return self._get_repository_info(owner, repo, headers)
            elif operation == "create_branch":
                return self._create_branch_from_default(owner, repo, headers, branch_name_prefix)
            elif operation == "get_file":
                if not file_path:
                    return json.dumps({"success": False, "error": "file_path is required for get_file operation"})
                return self._get_file_content(owner, repo, headers, file_path, source_branch)
            elif operation == "clone_repo":
                if not source_branch:
                    source_branch = "main"
                return self._clone_repository(owner, repo, github_token, source_branch, workspace_dir)
            elif operation == "commit_and_push":
                if not source_branch:
                    return json.dumps({"success": False, "error": "source_branch is required for commit_and_push operation"})
                if not commit_message:
                    return json.dumps({"success": False, "error": "commit_message is required for commit_and_push operation"})
                return self._commit_and_push(workspace_dir, commit_message, source_branch)
            elif operation == "create_pr":
                if not source_branch:
                    return json.dumps({"success": False, "error": "source_branch is required for create_pr operation"})
                return self._create_pull_request(owner, repo, headers, source_branch, target_branch, pr_title, pr_description)
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unknown operation: {operation}. Supported: get_repo_info, create_branch, get_file, clone_repo, commit_and_push, create_pr"
                })
                
        except Exception as e:
            return json.dumps({"success": False, "error": f"Unexpected error: {str(e)}"})

    def _parse_repository_url(self, url: str) -> Optional[tuple]:
        """Parse GitHub repository URL to extract owner and repo name."""
        try:
            url = url.rstrip('/')
            if url.endswith('.git'): url = url[:-4]
            parts = url.split('/')
            if len(parts) >= 2:
                return (parts[-2], parts[-1])
            return None
        except: return None

    def _get_repository_info(self, owner: str, repo: str, headers: dict) -> str:
        """Get repository information including default branch."""
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                repo_data = response.json()
                return json.dumps({
                    "success": True,
                    "repository_info": {
                        "name": repo_data.get("name"), "full_name": repo_data.get("full_name"),
                        "default_branch": repo_data.get("default_branch"), "private": repo_data.get("private"),
                        "clone_url": repo_data.get("clone_url")
                    }
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": f"Failed to get repository info. Status: {response.status_code}"})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})

    def _create_branch_from_default(self, owner: str, repo: str, headers: dict, branch_prefix: str) -> str:
        """Create a new branch from the repository's default branch."""
        try:
            repo_info_response = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
            if repo_info_response.status_code != 200:
                return json.dumps({"success": False, "error": "Failed to get repository info"})
            
            default_branch = repo_info_response.json().get("default_branch", "main")
            ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{default_branch}"
            ref_response = requests.get(ref_url, headers=headers)
            if ref_response.status_code != 200:
                return json.dumps({"success": False, "error": "Failed to get default branch reference"})
            
            default_sha = ref_response.json()["object"]["sha"]
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            new_branch_name = f"{branch_prefix}-{timestamp}"
            
            create_ref_data = {"ref": f"refs/heads/{new_branch_name}", "sha": default_sha}
            create_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs"
            create_response = requests.post(create_url, headers=headers, json=create_ref_data)
            
            if create_response.status_code == 201:
                return json.dumps({
                    "success": True,
                    "branch_created": {
                        "branch_name": new_branch_name, "source_branch": default_branch, "source_sha": default_sha
                    }
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": f"Failed to create branch. Status: {create_response.status_code}"})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})

    def _get_file_content(self, owner: str, repo: str, headers: dict, file_path: str, branch: str = None) -> str:
        """Get file contents from repository."""
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
            if branch: url += f"?ref={branch}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                file_data = response.json()
                content = base64.b64decode(file_data["content"]).decode('utf-8') if file_data.get("encoding") == "base64" else file_data.get("content", "")
                return json.dumps({"success": True, "file_info": {"path": file_data.get("path"), "content": content}}, indent=2)
            else:
                return json.dumps({"success": False, "error": f"Failed to get file content. Status: {response.status_code}"})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})

    def _clone_repository(self, owner: str, repo: str, token: str, branch: str, workspace_dir: str) -> str:
        """Clone the repository using local git command into REPO_DIR."""
        try:
            target_dir = REPO_DIR
            clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
            
            if os.path.exists(target_dir) and os.path.isdir(os.path.join(target_dir, ".git")):
                # Strategy: Fetch and pull instead of re-cloning
                cmds = [
                    f"git fetch origin",
                    f"git checkout {branch}",
                    f"git pull origin {branch}"
                ]
                outputs = []
                for cmd in cmds:
                    res = subprocess.run(cmd, shell=True, cwd=target_dir, capture_output=True, text=True)
                    outputs.append(f"Command: {cmd}\nOutput: {res.stdout}\nError: {res.stderr}")
                    if res.returncode != 0:
                        return json.dumps({"success": False, "error": f"Failed to update repo: {cmd}", "logs": outputs})
                
                return json.dumps({"success": True, "message": f"Successfully updated branch {branch} in {target_dir}", "logs": outputs})
            
            # If directory exists but not a git repo, or doesn't exist, clone it
            if os.path.exists(target_dir):
                import shutil
                shutil.rmtree(target_dir, ignore_errors=True)
            
            os.makedirs(os.path.dirname(target_dir), exist_ok=True)
            cmd = f"git clone -b {branch} {clone_url} {target_dir}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                return json.dumps({"success": True, "message": f"Successfully cloned branch {branch} into {target_dir}"})
            else:
                return json.dumps({"success": False, "error": f"Clone failed: {result.stderr}"})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})

    def _commit_and_push(self, workspace_dir: str, commit_message: str, branch: str) -> str:
        """Commit all changes in local workspace and push."""
        try:
            if not os.path.exists(workspace_dir):
                return json.dumps({"success": False, "error": "Workspace directory not found."})
            
            cmds = [
                "git config user.name 'CrewAI Agent'",
                "git config user.email 'crewai@agent.local'",
                "git add .",
                f"git commit -m \"{commit_message}\"",
                f"git push origin {branch}"
            ]
            
            outputs = []
            for cmd in cmds:
                res = subprocess.run(cmd, shell=True, cwd=workspace_dir, capture_output=True, text=True)
                outputs.append(res.stdout + res.stderr)
                if res.returncode != 0 and 'commit' not in cmd and 'nothing to commit' not in (res.stdout + res.stderr):
                    return json.dumps({"success": False, "error": f"Command failed: {cmd}\nOutput: {res.stderr}"})
            
            return json.dumps({"success": True, "message": "Successfully committed and pushed changes.", "logs": outputs})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})

    def _create_pull_request(self, owner: str, repo: str, headers: dict, source_branch: str, 
                           target_branch: str = None, title: str = None, description: str = None) -> str:
        """Create a pull request, validating branches beforehand."""
        try:
            if not target_branch:
                repo_response = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
                target_branch = repo_response.json().get("default_branch", "main") if repo_response.status_code == 200 else "main"
            
            # 1. Validate source branch exists
            source_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/branches/{source_branch}", headers=headers)
            if source_resp.status_code != 200:
                return json.dumps({"success": False, "error": f"Source branch '{source_branch}' does not exist on remote."})
                
            # 2. Validate target branch exists
            target_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/branches/{target_branch}", headers=headers)
            if target_resp.status_code != 200:
                return json.dumps({"success": False, "error": f"Target branch '{target_branch}' does not exist on remote."})
            
            # 3. Create PR
            data = {
                "title": title or f"Pull request from {source_branch}",
                "head": source_branch,
                "base": target_branch,
                "body": description or f"Automated pull request from {source_branch}"
            }
            
            response = requests.post(f"https://api.github.com/repos/{owner}/{repo}/pulls", headers=headers, json=data)
            if response.status_code == 201:
                return json.dumps({"success": True, "pull_request": {"number": response.json().get("number"), "html_url": response.json().get("html_url")}})
            else:
                return json.dumps({"success": False, "error": f"Failed to create PR. Status: {response.status_code}. Response: {response.text}"})
        except Exception as e: return json.dumps({"success": False, "error": str(e)})