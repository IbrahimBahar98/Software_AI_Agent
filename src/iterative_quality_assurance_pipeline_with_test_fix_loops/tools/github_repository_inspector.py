from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any, List
import requests
import json
import base64
import os

class GitHubRepositoryInspectorInput(BaseModel):
    """Input schema for GitHub Repository Inspector Tool."""
    action: str = Field(
        description="Action to perform: 'get_repo_info', 'get_file_content', 'list_contents', or 'get_branches'"
    )
    owner: str = Field(description="Repository owner (username or organization)")
    repo: str = Field(description="Repository name")
    file_path: Optional[str] = Field(default=None, description="File path for get_file_content action")
    path: Optional[str] = Field(default="", description="Directory path for list_contents action")
    branch: Optional[str] = Field(default="main", description="Branch name (defaults to 'main')")

class GitHubRepositoryInspector(BaseTool):
    """Tool for inspecting GitHub repositories via REST API.
    
    This tool provides comprehensive repository inspection capabilities including:
    - Repository information retrieval
    - File content reading
    - Directory structure navigation
    - Branch information access
    
    Supports both public and private repositories with proper authentication.
    """

    name: str = "GitHubRepositoryInspector"
    description: str = (
        "Inspects GitHub repositories using REST API. Can retrieve repository info, "
        "read file contents, list directory contents, and get branch information. "
        "Use action parameter to specify operation: 'get_repo_info', 'get_file_content', "
        "'list_contents', or 'get_branches'. Requires owner and repo parameters."
    )
    args_schema: Type[BaseModel] = GitHubRepositoryInspectorInput

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for GitHub API requests with optional authentication."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CrewAI-GitHub-Inspector"
        }
        
        # Add authentication if token is available
        token = os.environ.get("GITHUB_AUTH_TKN")
        if token:
            headers["Authorization"] = f"token {token}"
            
        return headers

    def _make_request(self, url: str) -> Dict[str, Any]:
        """Make a request to GitHub API with error handling."""
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            elif response.status_code == 404:
                return {"success": False, "error": "Repository, file, or branch not found"}
            elif response.status_code == 403:
                if "rate limit" in response.text.lower():
                    return {"success": False, "error": "GitHub API rate limit exceeded. Please try again later."}
                else:
                    return {"success": False, "error": "Access forbidden. Repository may be private or token invalid."}
            elif response.status_code == 401:
                return {"success": False, "error": "Authentication required. Please provide a valid GitHub token."}
            else:
                return {"success": False, "error": f"GitHub API error: {response.status_code} - {response.text[:200]}"}
                
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out. GitHub API may be slow."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection error. Please check your internet connection."}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_repository_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get general repository information."""
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
                    "stars": data.get("stargazers_count"),
                    "forks": data.get("forks_count"),
                    "open_issues": data.get("open_issues_count"),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "clone_url": data.get("clone_url"),
                    "topics": data.get("topics", [])
                }
            }
        return result

    def get_file_content(self, owner: str, repo: str, file_path: str, branch: str = "main") -> Dict[str, Any]:
        """Get the content of a specific file from the repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
        result = self._make_request(url)
        
        if result["success"]:
            data = result["data"]
            
            if data.get("type") == "file":
                try:
                    # Decode base64 content
                    content = base64.b64decode(data.get("content", "")).decode("utf-8")
                    return {
                        "success": True,
                        "file_content": {
                            "name": data.get("name"),
                            "path": data.get("path"),
                            "size": data.get("size"),
                            "content": content,
                            "encoding": data.get("encoding"),
                            "sha": data.get("sha"),
                            "download_url": data.get("download_url")
                        }
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to decode file content: {str(e)}"}
            else:
                return {"success": False, "error": f"Path '{file_path}' is not a file, it's a {data.get('type')}"}
        
        return result

    def list_repository_contents(self, owner: str, repo: str, path: str = "", branch: str = "main") -> Dict[str, Any]:
        """List contents of a repository directory."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        result = self._make_request(url)
        
        if result["success"]:
            data = result["data"]
            
            if isinstance(data, list):
                contents = []
                for item in data:
                    contents.append({
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                        "sha": item.get("sha"),
                        "download_url": item.get("download_url")
                    })
                
                return {
                    "success": True,
                    "contents": {
                        "path": path if path else "/",
                        "branch": branch,
                        "items": contents,
                        "total_items": len(contents)
                    }
                }
            else:
                return {"success": False, "error": f"Path '{path}' is a file, not a directory"}
        
        return result

    def get_repository_branches(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get list of repository branches."""
        url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        result = self._make_request(url)
        
        if result["success"]:
            data = result["data"]
            branches = []
            for branch in data:
                branches.append({
                    "name": branch.get("name"),
                    "sha": branch.get("commit", {}).get("sha"),
                    "protected": branch.get("protected", False)
                })
            
            return {
                "success": True,
                "branches": {
                    "total_branches": len(branches),
                    "branch_list": branches
                }
            }
        
        return result

    def _run(self, action: str, owner: str, repo: str, file_path: Optional[str] = None, 
            path: Optional[str] = "", branch: Optional[str] = "main") -> str:
        """Execute the requested GitHub repository operation."""
        
        # Validate required parameters
        if not owner or not repo:
            return json.dumps({
                "success": False,
                "error": "Owner and repository name are required parameters"
            })
        
        try:
            if action == "get_repo_info":
                result = self.get_repository_info(owner, repo)
                
            elif action == "get_file_content":
                if not file_path:
                    return json.dumps({
                        "success": False,
                        "error": "file_path parameter is required for get_file_content action"
                    })
                result = self.get_file_content(owner, repo, file_path, branch or "main")
                
            elif action == "list_contents":
                result = self.list_repository_contents(owner, repo, path or "", branch or "main")
                
            elif action == "get_branches":
                result = self.get_repository_branches(owner, repo)
                
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Invalid action: {action}. Valid actions are: get_repo_info, get_file_content, list_contents, get_branches"
                })
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Tool execution error: {str(e)}"
            })