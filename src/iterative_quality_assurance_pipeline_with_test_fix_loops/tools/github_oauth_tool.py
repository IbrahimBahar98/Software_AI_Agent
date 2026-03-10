from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import requests
import json
import time
import webbrowser
import os
import sys
import socket
import stat

try:
    from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
        GITHUB_OAUTH_CLIENT_ID, TOKEN_CACHE_DIR
    )
except ImportError:
    GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
    TOKEN_CACHE_DIR = os.path.expanduser("~/.config/crewai-qa")


class GitHubOAuthInput(BaseModel):
    """Input schema for GitHub OAuth Tool."""
    action: str = Field(default="get_token", description="Action: 'get_token' or 'clear_cache'")


class GitHubOAuthTool(BaseTool):
    """GitHub authentication via OAuth Device Flow with local token caching."""

    name: str = "github_oauth_tool"
    description: str = "Handles GitHub authentication via OAuth. Caches tokens locally."
    args_schema: Type[BaseModel] = GitHubOAuthInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not os.path.exists(TOKEN_CACHE_DIR):
            try:
                os.makedirs(TOKEN_CACHE_DIR, mode=0o700, exist_ok=True)
            except Exception:
                pass

    def _get_token_path(self):
        return os.path.join(TOKEN_CACHE_DIR, "github_token.json")

    def get_cached_token(self):
        """Read cached token from disk."""
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                with open(token_path, "r") as f:
                    data = json.load(f)
                    return data.get("access_token")
            except Exception:
                return None
        return None

    def _save_token(self, token: str):
        """Save token with restricted file permissions."""
        token_path = self._get_token_path()
        try:
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump({"access_token": token, "updated_at": time.time()}, f)
        except Exception:
            # Fallback for Windows where os.open mode may not work
            try:
                with open(token_path, "w") as f:
                    json.dump({"access_token": token, "updated_at": time.time()}, f)
            except Exception:
                pass

    def clear_cache(self):
        """Delete the cached token."""
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                os.remove(token_path)
                return "Token cache cleared."
            except Exception as e:
                return f"Failed to clear cache: {e}"
        return "No token cache found."

    def _run(self, action: str = "get_token") -> str:
        """Agent-facing tool execution."""
        if action == "clear_cache":
            return self.clear_cache()

        token = self.get_cached_token()
        if token:
            return "Authenticated. Token is cached."

        env_token = os.getenv("GITHUB_AUTH_TKN")
        if env_token:
            return "Authenticated via environment variable."

        return "Not authenticated. GITHUB_AUTH_TKN is missing and no cached token found."

    def _find_free_port(self, start=8080, end=8099):
        """Find an available port in range."""
        for port in range(start, end):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                continue
        return None

    def get_or_request_token_interactive(self) -> str:
        """Interactive OAuth flow with local redirect server."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import urllib.parse
        import threading

        if not GITHUB_OAUTH_CLIENT_ID:
            print("[X] GITHUB_OAUTH_CLIENT_ID not configured.")
            return input("Fallback: Paste your GitHub Token: ").strip()

        # 1. Check cache
        cached_token = self.get_cached_token()
        if cached_token:
            try:
                headers = {"Authorization": f"Bearer {cached_token}", "Accept": "application/vnd.github.v3+json"}
                test_resp = requests.get("https://api.github.com/user", headers=headers, timeout=5)
                if test_resp.status_code == 200:
                    # Verify scopes
                    scopes = test_resp.headers.get("X-OAuth-Scopes", "")
                    if "repo" in scopes:
                        print("[\033[92m✓\033[0m] Using existing GitHub session.")
                        return cached_token
                    else:
                        print(f"[!] Token has scopes: {scopes}. Missing 'repo'. Re-authenticating.")
                        self.clear_cache()
                else:
                    self.clear_cache()
            except Exception:
                pass

        # 2. Validate client secret before starting browser flow
        client_secret = os.getenv("GITHUB_CLIENT_SECRET")
        if not client_secret:
            print("[!] GITHUB_CLIENT_SECRET not set.")
            print("    If your OAuth App is private, token exchange will fail.")
            if sys.stdin.isatty():
                proceed = input("    Continue anyway? (y/N): ").strip().lower()
                if proceed != 'y':
                    return input("Fallback: Paste your GitHub Token: ").strip()

        # 3. Find free port
        port = self._find_free_port()
        if not port:
            print("[X] No free port in range 8080-8099.")
            return input("Fallback: Paste your GitHub Token: ").strip()

        # 4. Setup local server
        class OAuthHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if 'code' in params:
                    self.server.code = params['code'][0]
                    self.wfile.write(
                        b"<html><body style='font-family:sans-serif;text-align:center;padding-top:50px;'>"
                        b"<h1 style='color:#2ecc71;'>Success!</h1>"
                        b"<p>Authenticated. You can close this tab.</p></body></html>"
                    )
                else:
                    self.wfile.write(b"<html><body><h1>Auth Failed</h1></body></html>")

        try:
            server = HTTPServer(('localhost', port), OAuthHandler)
            server.code = None
        except Exception as e:
            print(f"[X] Could not start server on port {port}: {e}")
            return input("Fallback: Paste your GitHub Token: ").strip()

        # 5. Open browser
        redirect_uri = f"http://localhost:{port}"
        auth_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={GITHUB_OAUTH_CLIENT_ID}"
            f"&scope=repo%20user"
            f"&redirect_uri={redirect_uri}"
        )

        print(f"\n=== GitHub Browser Authentication (port {port}) ===")
        print("Opening browser...")
        webbrowser.open(auth_url)

        # 6. Wait for callback (handle multiple requests for favicon etc.)
        def wait_for_code():
            while server.code is None:
                server.handle_request()

        thread = threading.Thread(target=wait_for_code, daemon=True)
        thread.start()

        print("Waiting for authorization...", end="", flush=True)
        start_wait = time.time()
        while server.code is None and (time.time() - start_wait < 120):
            time.sleep(1)
            print(".", end="", flush=True)

        if not server.code:
            print("\n[X] Authentication timed out.")
            return input("Fallback: Paste your GitHub Token: ").strip()

        # 7. Exchange code for token
        try:
            resp = requests.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_OAUTH_CLIENT_ID,
                    "client_secret": client_secret or "",
                    "code": server.code,
                    "redirect_uri": redirect_uri
                },
                timeout=15
            )

            res_json = resp.json()
            if "access_token" in res_json:
                token = res_json["access_token"]
                print("\n[\033[92m✓\033[0m] Successfully authenticated!")
                self._save_token(token)
                return token
            else:
                error_desc = res_json.get('error_description', 'Unknown error')
                print(f"\n[X] Token exchange failed: {error_desc}")
                if "client_secret" in error_desc.lower() or res_json.get("error") == "incorrect_client_credentials":
                    print("    Set GITHUB_CLIENT_SECRET in your .env file.")
                return input("Fallback: Paste your GitHub Token: ").strip()

        except Exception as e:
            print(f"\n[X] Token exchange error: {e}")
            return input("Fallback: Paste your GitHub Token: ").strip()