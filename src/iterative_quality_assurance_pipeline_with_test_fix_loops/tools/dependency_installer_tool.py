"""
Generic dependency installer for the QA pipeline.

All per-language logic lives in _language_detector.TEST_FRAMEWORK_DETECTION.
This tool is a generic engine that for each detected language:
  1. Checks prerequisites (required files like package.json, Cargo.toml)
  2. Checks if each linter is installed (via check_cmd)
  3. Installs if missing (via install command)
  4. Checks if config exists (via config_files list)
  5. Creates config from template if missing (via config_template)

To support a new language: just add entries to TEST_FRAMEWORK_DETECTION.
Zero changes needed here.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any, List
import subprocess
import os
import json
import logging

from iterative_quality_assurance_pipeline_with_test_fix_loops.config import (
    REPO_DIR, MAX_BASH_TIMEOUT
)
from iterative_quality_assurance_pipeline_with_test_fix_loops.tools._language_detector import (
    detect_languages, TEST_FRAMEWORK_DETECTION
)

logger = logging.getLogger(__name__)


class DependencyInstallerInput(BaseModel):
    """Input schema for Dependency Installer Tool."""
    repo_path: str = Field(
        description="Absolute path to the repository root directory."
    )
    install_linters: bool = Field(
        default=True,
        description="Install missing linter tools."
    )
    install_test_frameworks: bool = Field(
        default=True,
        description="Install missing test framework dependencies."
    )
    create_configs: bool = Field(
        default=True,
        description="Create missing config files from templates."
    )


class DependencyInstallerTool(BaseTool):
    """
    Generic dependency installer — auto-detects languages and installs
    all missing linters, test frameworks, and config files.
    
    Driven entirely by _language_detector.TEST_FRAMEWORK_DETECTION data.
    """

    name: str = "dependency_installer_tool"
    description: str = (
        "Auto-detects project languages and installs ALL missing dependencies: "
        "linters (ruff, eslint, cppcheck, clippy, etc.), test frameworks "
        "(pytest, jest, junit, etc.), and creates missing config files "
        "(.eslintrc.json, etc.). Provide the repo_path to analyze."
    )
    args_schema: Type[BaseModel] = DependencyInstallerInput

    # ── Shell execution ───────────────────────────────────

    def _exec(self, cmd: str, cwd: str, timeout: int = None) -> Dict[str, Any]:
        """Run a shell command. Returns {success, output, exit_code}."""
        timeout = timeout or MAX_BASH_TIMEOUT
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1"},
            )
            output = (result.stdout + result.stderr).strip()
            return {
                "success": result.returncode == 0,
                "output": output[:500] if output else "(no output)",
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": f"Timed out after {timeout}s", "exit_code": -1}
        except Exception as e:
            return {"success": False, "output": f"{type(e).__name__}: {e}", "exit_code": -1}

    # ── Generic checks ────────────────────────────────────

    def _check_prerequisites(self, requires: List[str], cwd: str) -> Optional[str]:
        """Check if prerequisite files exist. Returns error msg or None."""
        for req in requires:
            if not os.path.exists(os.path.join(cwd, req)):
                return f"'{req}' not found in {cwd}"
        return None

    def _is_installed(self, check_cmd: str, cwd: str) -> bool:
        """Run check_cmd to verify a tool is available."""
        if not check_cmd:
            return True  # No check defined → assume present
        return self._exec(check_cmd, cwd, timeout=30)["success"]

    def _install(self, install_cmd: str, cwd: str) -> Dict[str, Any]:
        """Run install_cmd with extended timeout for npm/pip."""
        if not install_cmd:
            return {"success": False, "output": "No install command defined"}
        return self._exec(install_cmd, cwd, timeout=180)

    # ── Generic config management ─────────────────────────

    def _has_config(self, tool_info: Dict, cwd: str) -> bool:
        """
        Check if a tool's config exists.
        Looks at:
          - config_files: list of filenames to check
          - config_pkg_json_key: key inside package.json
        If neither is defined, config is not required → returns True.
        """
        config_files = tool_info.get("config_files", [])
        pkg_key = tool_info.get("config_pkg_json_key")

        # Check standalone config files
        for cf in config_files:
            if os.path.exists(os.path.join(cwd, cf)):
                return True

        # Check package.json key
        if pkg_key:
            pkg_path = os.path.join(cwd, "package.json")
            if os.path.exists(pkg_path):
                try:
                    with open(pkg_path, "r", encoding="utf-8") as f:
                        pkg = json.load(f)
                    if pkg_key in pkg:
                        return True
                except Exception:
                    pass

        # Nothing to check → not required
        if not config_files and not pkg_key:
            return True

        return False

    def _detect_source_type(self, cwd: str) -> str:
        """Read package.json 'type' field to determine JS module system."""
        pkg_path = os.path.join(cwd, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8") as f:
                    pkg = json.load(f)
                if pkg.get("type") == "module":
                    return "module"
            except Exception:
                pass
        return "commonjs"

    def _create_config(self, tool_info: Dict, cwd: str) -> Optional[str]:
        """
        Create a config file from config_template if available.
        Auto-sets parserOptions.sourceType if missing.
        Returns status message or None.
        """
        template = tool_info.get("config_template")
        if not template:
            return None

        # Pick output filename (prefer .json)
        config_files = tool_info.get("config_files", [])
        if not config_files:
            return None

        out_file = None
        for cf in config_files:
            if cf.endswith(".json"):
                out_file = cf
                break
        if not out_file:
            out_file = config_files[0]

        out_path = os.path.join(cwd, out_file)

        # Deep-copy template
        config = json.loads(json.dumps(template))

        # Auto-detect sourceType if parserOptions present but sourceType missing
        parser_opts = config.get("parserOptions", {})
        if "parserOptions" in config and "sourceType" not in parser_opts:
            parser_opts["sourceType"] = self._detect_source_type(cwd)
            config["parserOptions"] = parser_opts

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return f"Created {out_file}"
        except Exception as e:
            return f"Failed to create {out_file}: {e}"

    def _ensure_ignore_files(self, tool_info: Dict, cwd: str) -> List[str]:
        """
        Create ignore files (like .eslintignore) if they don't exist.
        """
        ignore_files = tool_info.get("ignore_files", [])
        ignore_content = tool_info.get("ignore_content", "")
        if not ignore_files or not ignore_content:
            return []

        created = []
        for ifile in ignore_files:
            ipath = os.path.join(cwd, ifile)
            if not os.path.exists(ipath):
                try:
                    with open(ipath, "w", encoding="utf-8") as f:
                        f.write(ignore_content)
                    created.append(f"Created {ifile}")
                except Exception as e:
                    created.append(f"Failed to create {ifile}: {e}")
        return created

    # ── Generic per-tool installer ────────────────────────

    def _process_tool(
        self, tool_name: str, tool_info: Dict, cwd: str, create_configs: bool
    ) -> Dict[str, Any]:
        """
        Generic pipeline for a single tool:
          1. Check prerequisites
          2. Check installed → install if needed
          3. Check config → create if needed
        """
        entry = {
            "tool": tool_name,
            "actions": [],
            "status": "ok",
        }

        # 1. Prerequisites
        requires = tool_info.get("requires", [])
        prereq_err = self._check_prerequisites(requires, cwd)
        if prereq_err:
            entry["actions"].append(f"SKIP: {prereq_err}")
            entry["status"] = "skipped"
            return entry

        # 2. Check installed
        check_cmd = tool_info.get("check_cmd", "")
        install_cmd = tool_info.get("install", "")

        if not self._is_installed(check_cmd, cwd):
            if install_cmd:
                entry["actions"].append(f"Installing {tool_name}...")
                result = self._install(install_cmd, cwd)
                if result["success"]:
                    entry["actions"].append(f"Installed {tool_name}")
                    # Verify
                    if check_cmd and not self._is_installed(check_cmd, cwd):
                        entry["actions"].append(f"WARNING: {tool_name} still not found after install")
                        entry["status"] = "install_failed"
                        return entry
                else:
                    entry["actions"].append(f"Install failed: {result['output'][:200]}")
                    entry["status"] = "install_failed"
                    return entry
            else:
                entry["actions"].append(f"{tool_name} not found, no install command defined")
                entry["status"] = "skipped"
                return entry
        else:
            entry["actions"].append(f"{tool_name} already installed")

        # 3. Config check
        if create_configs:
            # Check for standard configs
            if not self._has_config(tool_info, cwd):
                msg = self._create_config(tool_info, cwd)
                if msg:
                    entry["actions"].append(msg)
                else:
                    entry["actions"].append(f"No config for {tool_name}, no template available")
            else:
                entry["actions"].append(f"Config for {tool_name} already exists")
            
            # Check/create ignore files
            ignore_msgs = self._ensure_ignore_files(tool_info, cwd)
            entry["actions"].extend(ignore_msgs)

        return entry

    # ── Main entry point ──────────────────────────────────

    def _run(
        self,
        repo_path: str,
        install_linters: bool = True,
        install_test_frameworks: bool = True,
        create_configs: bool = True,
    ) -> str:
        if not os.path.exists(repo_path):
            return json.dumps({
                "success": False,
                "error": f"Repository path '{repo_path}' not found",
            })

        cwd = os.path.abspath(repo_path)
        languages = detect_languages(cwd)

        report = {
            "success": True,
            "repo_path": cwd,
            "languages_detected": languages,
            "linters": {},
            "test_frameworks": {},
            "summary": {
                "installed": 0,
                "already_present": 0,
                "skipped": 0,
                "failed": 0,
                "configs_created": 0,
            },
        }

        if not languages:
            report["success"] = False
            report["error"] = "No recognized languages detected"
            return json.dumps(report, indent=2)

        for lang in languages:
            lang_config = TEST_FRAMEWORK_DETECTION.get(lang, {})

            # Process linters
            if install_linters:
                for linter_name, linter_info in lang_config.get("linters", {}).items():
                    key = f"{lang}/{linter_name}"
                    entry = self._process_tool(linter_name, linter_info, cwd, create_configs)
                    report["linters"][key] = entry

                    # Update summary
                    if entry["status"] == "ok":
                        if any("Installed" in a for a in entry["actions"]):
                            report["summary"]["installed"] += 1
                        else:
                            report["summary"]["already_present"] += 1
                        if any("Created" in a for a in entry["actions"]):
                            report["summary"]["configs_created"] += 1
                    elif entry["status"] == "skipped":
                        report["summary"]["skipped"] += 1
                    else:
                        report["summary"]["failed"] += 1
                        report["success"] = False

            # Process test frameworks
            if install_test_frameworks:
                for fw_name, fw_info in lang_config.get("frameworks", {}).items():
                    key = f"{lang}/{fw_name}"
                    # Frameworks don't usually have check_cmd/config_template
                    # but the generic engine handles missing fields gracefully
                    fw_tool_info = {
                        "check_cmd": "",  # No standard way to check
                        "install": fw_info.get("install", ""),
                        "requires": [],
                    }
                    if fw_info.get("install"):
                        entry = self._process_tool(fw_name, fw_tool_info, cwd, False)
                        report["test_frameworks"][key] = entry

        s = report["summary"]
        report["summary_text"] = (
            f"Installed: {s['installed']}, "
            f"Already present: {s['already_present']}, "
            f"Skipped: {s['skipped']}, "
            f"Failed: {s['failed']}, "
            f"Configs created: {s['configs_created']}"
        )

        return json.dumps(report, indent=2)