from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any, List
import requests
import json
import base64
import os
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    HTTP_REQUEST_TIMEOUT, MAX_FILE_CONTENT_CHARS
)


class GitHubRepositoryInspectorInput(BaseModel):
    """Input schema for GitHub Repository Inspector Tool."""
    action: str = Field(
        description="Action: 'get_repo_info', 'get_file_content', 'list_contents', or 'get_branches'"
    )
    owner: str = Field(description="Repository owner (username or organization)")
    repo: str = Field(description="Repository name")
    file_path: Optional[str] = Field(default=None, description="File path for get_file_content")
    path: Optional[str] = Field(default="", description="Directory path for list_contents")
    branch: Optional[str] = Field(default="main", description="Branch name")


class GitHubRepositoryInspector(BaseTool):
    """Tool for inspecting GitHub repositories via REST API."""

    name: str = "GitHubRepositoryInspector"
    description: str = (
        "Inspects GitHub repositories via REST API. Actions: 'get_repo_info', "
        "'get_file_content', 'list_contents', 'get_branches'. "
        "NOTE: Large files are automatically truncated. For full file contents, "
        "use bash_execution_tool to read the local clone instead."
    )
    args_schema: Type[BaseModel] = GitHubRepositoryInspectorInput

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CrewAI-GitHub-Inspector"
        }
        token = os.environ.get("GITHUB_AUTH_TKN")
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def _make_request(self, url: str) -> Dict[str, Any]:
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=HTTP_REQUEST_TIMEOUT)
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            elif response.status_code == 404:
                return {"success": False, "error": "Not found (404)"}
            elif response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining", "?")
                if "rate limit" in response.text.lower():
                    return {"success": False, "error": f"Rate limited. Remaining: {remaining}. Try again later."}
                return {"success": False, "error": "Access forbidden (403). Token may lack permissions."}
            elif response.status_code == 401:
                return {"success": False, "error": "Authentication required (401)."}
            else:
                return {"success": False, "error": f"GitHub API error {response.status_code}: {response.text[:200]}"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection error."}
        except Exception as e:
            return {"success": False, "error": f"Request error: {str(e)}"}

    def get_repository_info(self, owner: str, repo: str) -> Dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        result = self._make_request(url)
        if result["success"]:
            data = result["data"]
            return {
                "success": True,
                "repository_info": {
                    "name": data.get("name"),
                    "full_name": data.get("full_name"),
                    "description": data.get("description"),
                    "private": data.get("private"),
                    "owner": data.get("owner", {}).get("login"),
                    "default_branch": data.get("default_branch"),
                    "language": data.get("language"),
                    "size": data.get("size"),
                    "clone_url": data.get("clone_url"),
                    "topics": data.get("topics", [])
                }
            }
        return result

    def get_file_content(self, owner: str, repo: str, file_path: str, branch: str = "main") -> Dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
        result = self._make_request(url)
        if result["success"]:
            data = result["data"]
            if data.get("type") == "file":
                try:
                    content = base64.b64decode(data.get("content", "")).decode("utf-8")
                    truncated = False
                    original_size = len(content)
                    if len(content) > MAX_FILE_CONTENT_CHARS:
                        truncated = True
                        half = MAX_FILE_CONTENT_CHARS // 2
                        content = (
                            content[:half] +
                            f"\n\n... [TRUNCATED: {original_size} chars total. "
                            f"Use bash_execution_tool to read full file locally] ...\n\n" +
                            content[-half:]
                        )
                    return {
                        "success": True,
                        "file_content": {
                            "name": data.get("name"),
                            "path": data.get("path"),
                            "size": data.get("size"),
                            "content": content,
                            "truncated": truncated,
                            "original_size": original_size,
                        }
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to decode: {str(e)}"}
            else:
                return {"success": False, "error": f"'{file_path}' is a {data.get('type')}, not a file"}
        return result

    def list_repository_contents(self, owner: str, repo: str, path: str = "", branch: str = "main") -> Dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        result = self._make_request(url)
        if result["success"]:
            data = result["data"]
            if isinstance(data, list):
                contents = [
                    {"name": item.get("name"), "path": item.get("path"),
                     "type": item.get("type"), "size": item.get("size")}
                    for item in data
                ]
                return {
                    "success": True,
                    "contents": {
                        "path": path or "/",
                        "branch": branch,
                        "items": contents,
                        "total_items": len(contents)
                    }
                }
            return {"success": False, "error": f"'{path}' is a file, not a directory"}
        return result

    def get_repository_branches(self, owner: str, repo: str) -> Dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        result = self._make_request(url)
        if result["success"]:
            branches = [
                {"name": b.get("name"), "sha": b.get("commit", {}).get("sha"),
                 "protected": b.get("protected", False)}
                for b in result["data"]
            ]
            return {"success": True, "branches": {"total": len(branches), "list": branches}}
        return result

    def _run(self, action: str, owner: str, repo: str, file_path: Optional[str] = None,
             path: Optional[str] = "", branch: Optional[str] = "main") -> str:
        if not owner or not repo:
            return json.dumps({"success": False, "error": "owner and repo are required"})
        try:
            if action == "get_repo_info":
                result = self.get_repository_info(owner, repo)
            elif action == "get_file_content":
                if not file_path:
                    return json.dumps({"success": False, "error": "file_path required"})
                result = self.get_file_content(owner, repo, file_path, branch or "main")
            elif action == "list_contents":
                result = self.list_repository_contents(owner, repo, path or "", branch or "main")
            elif action == "get_branches":
                result = self.get_repository_branches(owner, repo)
            else:
                return json.dumps({"success": False, "error": f"Unknown action: {action}"})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": f"Error: {str(e)}"})
