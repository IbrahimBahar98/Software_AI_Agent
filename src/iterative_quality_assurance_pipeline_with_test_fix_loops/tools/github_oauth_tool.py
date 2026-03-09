from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import requests
import json
import time
import webbrowser
import os
import sys

# Import the config using absolute import if possible, fallback to relative
try:
    from iterative_quality_assurance_pipeline_with_test_fix_loops.config import GITHUB_OAUTH_CLIENT_ID, TOKEN_CACHE_DIR
except ImportError:
    # Fallback for direct execution
    GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "Iv23liBqUhwQ2xS0N4wY")
    TOKEN_CACHE_DIR = os.path.expanduser("~/.config/crewai-qa")

class GitHubOAuthInput(BaseModel):
    """Input schema for GitHub OAuth Tool."""
    action: str = Field(default="get_token", description="Action to perform: 'get_token' or 'clear_cache'")

class GitHubOAuthTool(BaseTool):
    """Tool for authenticating with GitHub using OAuth Device Flow.
    
    This replaces the need for users to manually create and paste Personal Access Tokens.
    It opens a browser for the user to authorize the app, then caches the token locally.
    """

    name: str = "github_oauth_tool"
    description: str = "Handles GitHub authentication via OAuth Device Flow. Caches tokens locally."
    args_schema: Type[BaseModel] = GitHubOAuthInput
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not os.path.exists(TOKEN_CACHE_DIR):
            try:
                os.makedirs(TOKEN_CACHE_DIR, exist_ok=True)
            except Exception:
                pass

    def _get_token_path(self):
        return os.path.join(TOKEN_CACHE_DIR, "github_token.json")

    def get_cached_token(self):
        """Read the cached token from disk if it exists."""
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                with open(token_path, "r") as f:
                    data = json.load(f)
                    return data.get("access_token")
            except Exception:
                return None
        return None

    def clear_cache(self):
        """Delete the cached token."""
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                os.remove(token_path)
                return "✅ Token cache cleared."
            except Exception as e:
                return f"❌ Failed to clear token cache: {e}"
        return "ℹ️ No token cache found."

    def _run(self, action: str = "get_token") -> str:
        """Execute the requested tool action (internal agent use)."""
        if action == "clear_cache":
            return self.clear_cache()
            
        token = self.get_cached_token()
        if token:
            return "✅ Authenticated. Token is cached and available in environment as GITHUB_AUTH_TKN."
            
        # For agent execution, we shouldn't trigger the interactive flow
        # The interactive flow should only be called from main.py before the crew starts
        env_token = os.getenv("GITHUB_AUTH_TKN")
        if env_token:
            return "✅ Authenticated via environment variable."
            
        return "❌ Not authenticated. GITHUB_AUTH_TKN is missing and no cached token found."

    def get_or_request_token_interactive(self) -> str:
        """Interactive function that starts a local server to catch the login (VS Code style)."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import urllib.parse
        import threading

        # 1. Check local cache
        cached_token = self.get_cached_token()
        if cached_token:
            headers = {"Authorization": f"Bearer {cached_token}", "Accept": "application/vnd.github.v3+json"}
            try:
                test_resp = requests.get("https://api.github.com/user", headers=headers, timeout=5)
                if test_resp.status_code == 200:
                    print("[\033[92m✓\033[0m] Using existing GitHub session.")
                    return cached_token
                else:
                    self.clear_cache()
            except Exception:
                pass

        # 2. Setup Local Redirect Server
        class OAuthHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): return # Silent
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if 'code' in params:
                    self.server.code = params['code'][0]
                    self.wfile.write(b"<html><body style='font-family:sans-serif;text-align:center;padding-top:50px;'>")
                    self.wfile.write(b"<h1 style='color:#2ecc71;'>Success!</h1><p>GitHub authenticated successfully. You can close this tab now.</p></body></html>")
                else:
                    self.wfile.write(b"<html><body><h1>Auth Failed</h1></body></html>")

        try:
            server = HTTPServer(('localhost', 8080), OAuthHandler)
            server.code = None
        except Exception as e:
            print(f"[\033[91mX\033[0m] Could not start local server on port 8080: {e}")
            return input("Fallback: Paste your GitHub Token: ").strip()
        
        # 3. Open Browser
        auth_url = (f"https://github.com/login/oauth/authorize"
                   f"?client_id={GITHUB_OAUTH_CLIENT_ID}"
                   f"&scope=repo%20user"
                   f"&redirect_uri=http://localhost:8080")
        
        print("\n=== GitHub Browser Authentication ===")
        print(f"Opening browser to authorize this project...")
        webbrowser.open(auth_url)
        
        # 4. Wait for callback
        def wait_for_code():
            server.handle_request()
        
        thread = threading.Thread(target=wait_for_code)
        thread.daemon = True
        thread.start()
        
        print("Waiting for you to click 'Authorize' in your browser...", end="", flush=True)
        # Timeout after 2 minutes
        start_wait = time.time()
        while server.code is None and (time.time() - start_wait < 120):
            time.sleep(1)
            print(".", end="", flush=True)

        if not server.code:
            print("\n[\033[91mX\033[0m] Authentication timed out or failed.")
            return input("Fallback: Paste your GitHub Token: ").strip()

        # 5. Exchange code for token
        token_url = "https://github.com/login/oauth/access_token"
        client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")
        
        resp = requests.post(token_url, headers={"Accept": "application/json"}, data={
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "client_secret": client_secret,
            "code": server.code,
            "redirect_uri": "http://localhost:8080"
        })
        
        res_json = resp.json()
        if "access_token" in res_json:
            token = res_json["access_token"]
            print("\n[\033[92m✓\033[0m] Successfully authenticated!")
            # Cache it
            token_path = self._get_token_path()
            try:
                with open(token_path, "w") as f:
                    json.dump({"access_token": token, "updated_at": time.time()}, f)
            except Exception: pass
            return token
        else:
            print(f"\n[\033[91mX\033[0m] Token exchange failed: {res_json.get('error_description', 'Missing Client Secret?')}")
            print("Tip: If your GitHub App is 'Private', you must add GITHUB_CLIENT_SECRET to your .env file.")
            return input("Fallback: Paste your GitHub Token: ").strip()

        return "" # Should not reach here
