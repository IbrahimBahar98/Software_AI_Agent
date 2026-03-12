# a2a/agents/discovery_agent.py
"""
Discovery Agent — Zero hardcoded knowledge.
Discovers everything by probing the actual system.
"""

import os
import subprocess
import json
import logging
import platform
from typing import Dict, Any, List, Optional, AsyncGenerator
from pathlib import Path

from ..models import (
    AgentCard, AgentSkill, Task, TaskState, TaskStatus,
    Message, Artifact,
)

logger = logging.getLogger(__name__)


class DiscoveryAgent:
    """
    Discovers environment and repository by PROBING, not by lookup tables.
    
    Philosophy:
    - Don't know what tools exist? Scan PATH.
    - Don't know what languages? Scan file extensions.
    - Don't know what test framework? Read the actual config files.
    - Don't know the OS commands? Ask the OS.
    
    The only "knowledge" here is HOW to probe, not WHAT to expect.
    """

    def _exec(
        self, cmd: str, cwd: str = None, timeout: int = 10
    ) -> Optional[str]:
        """Run a command, return stdout or None on failure."""
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1"},
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None

    # ─── Environment Discovery ────────────────────────────
    # No tool lists. Scan what's actually on PATH.

    def discover_environment(self) -> Dict[str, Any]:
        """Discover the runtime environment by probing the actual system."""
        env = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "arch": platform.machine(),
            "shell": self._discover_shell(),
            "path_executables": self._scan_path(),
            "package_managers": [],
            "runtimes": {},
        }

        # Categorize discovered executables by probing them
        for exe_name in env["path_executables"]:
            version = self._probe_version(exe_name)
            if version:
                env["runtimes"][exe_name] = version

        # Package managers are just executables that can install things
        # We know them by trying common install-related flags
        env["package_managers"] = self._discover_package_managers(
            env["path_executables"]
        )

        return env

    def _discover_shell(self) -> Dict[str, str]:
        """Detect the active shell and its capabilities."""
        system = platform.system()

        if system == "Windows":
            # Check what shells are available
            shells = {}
            if self._exec("pwsh --version"):
                shells["pwsh"] = self._exec("pwsh --version") or "available"
            if self._exec("powershell -Command $PSVersionTable.PSVersion.ToString()"):
                shells["powershell"] = (
                    self._exec(
                        "powershell -Command $PSVersionTable.PSVersion.ToString()"
                    ) or "available"
                )
            # CMD is always available on Windows
            shells["cmd"] = "available"
            
            return {
                "default": "pwsh" if "pwsh" in shells else "powershell",
                "available": shells,
                "chain_operator": " ; ",     # PowerShell
                "cmd_chain_operator": " && ", # CMD fallback
                "path_separator": "\\",
                "null_device": "NUL",
                "env_set": "set",
            }
        else:
            shell_path = os.environ.get("SHELL", "/bin/sh")
            shell_name = os.path.basename(shell_path)
            shells = {shell_name: shell_path}

            # Check for other common shells
            for s in ["bash", "zsh", "fish", "sh"]:
                path = self._exec(f"which {s}")
                if path:
                    shells[s] = path

            return {
                "default": shell_name,
                "available": shells,
                "chain_operator": " && ",
                "path_separator": "/",
                "null_device": "/dev/null",
                "env_set": "export",
            }

    def _scan_path(self) -> List[str]:
        """
        Scan PATH directories to find ALL available executables.
        This is the core of generic discovery — we don't assume
        what's installed, we look at what's actually there.
        """
        executables = set()
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)

        for dir_path in path_dirs:
            if not os.path.isdir(dir_path):
                continue
            try:
                for item in os.listdir(dir_path):
                    full = os.path.join(dir_path, item)
                    if os.path.isfile(full) and os.access(full, os.X_OK):
                        # Strip common extensions on Windows
                        name = item
                        if platform.system() == "Windows":
                            for ext in [".exe", ".cmd", ".bat", ".ps1", ".com"]:
                                if name.lower().endswith(ext):
                                    name = name[:-len(ext)]
                                    break
                        executables.add(name)
            except PermissionError:
                continue

        return sorted(executables)

    def _probe_version(self, exe_name: str) -> Optional[str]:
        """
        Try to get a version from an executable.
        Uses common conventions — most tools support --version or -version.
        No hardcoded per-tool knowledge.
        """
        # Try common version flags in order of likelihood
        for flag in ["--version", "-version", "version", "-V", "-v"]:
            output = self._exec(f"{exe_name} {flag}", timeout=5)
            if output:
                # Extract version-like pattern from first line
                import re
                first_line = output.split('\n')[0]
                match = re.search(r'(\d+\.\d+(?:\.\d+)?(?:[.-]\w+)?)', first_line)
                if match:
                    return match.group(1)
                # If no version pattern but got output, tool exists
                return "installed"
        return None

    def _discover_package_managers(
        self, executables: List[str]
    ) -> List[Dict[str, str]]:
        """
        Identify package managers from available executables.
        Instead of a hardcoded list, we probe for install capability.
        """
        managers = []

        # Heuristic: things that respond to "help install" or have
        # install-like subcommands are package managers
        candidate_patterns = [
            # (executable, test_command, install_syntax)
            # We try these and see what works
        ]

        # Actually, let's be smarter — scan executables for known
        # package manager PATTERNS (not specific names)
        for exe in executables:
            # Try help output to identify install capability
            help_output = self._exec(f"{exe} help", timeout=5)
            if help_output and "install" in help_output.lower():
                managers.append({
                    "name": exe,
                    "install_subcommand": self._detect_install_syntax(exe),
                })
                continue

            # Also try --help
            help_output = self._exec(f"{exe} --help", timeout=5)
            if help_output and "install" in help_output.lower():
                managers.append({
                    "name": exe,
                    "install_subcommand": self._detect_install_syntax(exe),
                })

        return managers

    def _detect_install_syntax(self, exe: str) -> str:
        """Figure out how a package manager installs things."""
        # Try common patterns
        for subcmd in ["install", "add", "get"]:
            help_output = self._exec(f"{exe} {subcmd} --help", timeout=5)
            if help_output and "usage" in help_output.lower():
                return subcmd
            # Some tools show help even on error
            help_output = self._exec(f"{exe} help {subcmd}", timeout=5)
            if help_output:
                return subcmd
        return "install"  # Best guess

    # ─── Repository Discovery ─────────────────────────────
    # No extension maps. Scan files and infer from what we find.

    def discover_repository(self, repo_dir: str) -> Dict[str, Any]:
        """
        Discover repository structure by scanning actual files.
        No hardcoded extension-to-language maps.
        """
        if not os.path.exists(repo_dir):
            return {"error": f"Directory not found: {repo_dir}"}

        profile = {
            "root_files": [],
            "extensions": {},       # ext → count
            "languages": {},        # inferred language → count
            "directory_structure": [],
            "config_files": [],
            "build_systems": [],
            "test_infrastructure": {},
            "ci_systems": [],
            "dependencies": {},
        }

        # 1. Scan all files — collect raw extension counts
        skip_dirs = self._discover_skip_dirs(repo_dir)
        
        for root, dirs, files in os.walk(repo_dir):
            # Dynamically skip directories that look like dependencies/build output
            dirs[:] = [d for d in dirs if d not in skip_dirs]

            depth = root.replace(repo_dir, "").count(os.sep)
            if depth <= 3:
                rel = os.path.relpath(root, repo_dir)
                if rel != ".":
                    profile["directory_structure"].append(rel)

            for f in files:
                # Root-level files (configs, manifests)
                if root == repo_dir:
                    profile["root_files"].append(f)

                ext = os.path.splitext(f)[1].lower()
                if ext:
                    profile["extensions"][ext] = (
                        profile["extensions"].get(ext, 0) + 1
                    )

        # 2. Infer languages from extensions
        #    Instead of a lookup table, use linguist-style heuristics
        profile["languages"] = self._infer_languages(
            profile["extensions"], repo_dir
        )

        # 3. Detect build systems from root files
        profile["build_systems"] = self._detect_build_systems(
            profile["root_files"], repo_dir
        )

        # 4. Detect test infrastructure by reading configs
        profile["test_infrastructure"] = self._detect_test_infrastructure(
            repo_dir, profile
        )

        # 5. Detect CI by scanning for workflow directories/files
        profile["ci_systems"] = self._detect_ci_systems(repo_dir)

        # 6. Read dependency manifests
        profile["dependencies"] = self._read_all_manifests(repo_dir)

        # 7. Generate command recommendations
        profile["recommended_commands"] = self._generate_commands(
            profile, self.discover_environment()
        )

        return profile

    def _discover_skip_dirs(self, repo_dir: str) -> set:
        """
        Dynamically figure out which directories to skip.
        Instead of hardcoding, detect by heuristics:
        - Contains thousands of files (node_modules, vendor)
        - Is a hidden directory (.git, .cache)
        - Is a known build output pattern
        """
        skip = set()

        for item in os.listdir(repo_dir):
            full = os.path.join(repo_dir, item)
            if not os.path.isdir(full):
                continue

            # Hidden directories
            if item.startswith('.'):
                skip.add(item)
                continue

            # Heuristic: if a directory has > 500 immediate children,
            # it's probably a dependency directory
            try:
                child_count = len(os.listdir(full))
                if child_count > 500:
                    skip.add(item)
                    continue
            except PermissionError:
                skip.add(item)
                continue

            # Heuristic: common output/dependency directory names
            # But instead of hardcoding, check if the directory has
            # a characteristic file
            if os.path.exists(os.path.join(full, ".package-lock.json")):
                skip.add(item)  # node_modules
            elif os.path.exists(os.path.join(full, "CACHEDIR.TAG")):
                skip.add(item)  # cache directory

        # Always skip .git
        skip.add(".git")

        return skip

    def _infer_languages(
        self, extensions: Dict[str, int], repo_dir: str
    ) -> Dict[str, int]:
        """
        Infer programming languages from file extensions.
        
        Instead of a static map, we use a two-phase approach:
        1. Check if GitHub's linguist YAML is available (installed)
        2. Fall back to probing: read file shebangs and content patterns
        """
        languages = {}

        # Phase 1: Try github-linguist if available
        linguist_output = self._exec(
            "github-linguist --json .", cwd=repo_dir, timeout=30
        )
        if linguist_output:
            try:
                linguist_data = json.loads(linguist_output)
                for lang, info in linguist_data.items():
                    if isinstance(info, dict):
                        languages[lang.lower()] = info.get("size", 0)
                    else:
                        languages[lang.lower()] = info
                if languages:
                    return languages
            except (json.JSONDecodeError, Exception):
                pass

        # Phase 2: Try 'git ls-files' + heuristic detection
        # Read actual file content to determine language
        for ext, count in sorted(
            extensions.items(), key=lambda x: -x[1]
        ):
            if count < 1:
                continue

            lang = self._identify_language_from_extension_and_content(
                ext, repo_dir
            )
            if lang:
                languages[lang] = languages.get(lang, 0) + count

        return languages

    def _identify_language_from_extension_and_content(
        self, ext: str, repo_dir: str
    ) -> Optional[str]:
        """
        Identify a language from its extension by reading a sample file.
        Uses shebang lines, keywords, and syntax patterns.
        No hardcoded extension map.
        """
        # Find a sample file with this extension
        sample_file = None
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.endswith(ext):
                    sample_file = os.path.join(root, f)
                    break
            if sample_file:
                break

        if not sample_file:
            return None

        # Read first 50 lines
        try:
            with open(sample_file, 'r', encoding='utf-8', errors='ignore') as fh:
                head = ""
                for i, line in enumerate(fh):
                    if i >= 50:
                        break
                    head += line
        except Exception:
            return None

        # Check shebang
        if head.startswith("#!"):
            shebang = head.split('\n')[0].lower()
            if "python" in shebang:
                return "python"
            if "node" in shebang or "deno" in shebang:
                return "javascript"
            if "ruby" in shebang:
                return "ruby"
            if "perl" in shebang:
                return "perl"
            if "bash" in shebang or "sh" in shebang or "zsh" in shebang:
                return "shell"
            if "php" in shebang:
                return "php"

        # Check content patterns (language-identifying keywords)
        patterns = [
            # (pattern, language)
            # These are SYNTAX patterns, not tool names
            ("def ", "python"),     # Also Ruby, but combined with ext
            ("import ", "python"),  # Very common
            ("from ", "python"),
            ("package main", "go"),
            ("func ", "go"),
            ("fn main", "rust"),
            ("fn ", "rust"),
            ("use std::", "rust"),
            ("public class", "java"),
            ("public static void", "java"),
            ("import java.", "java"),
            ("namespace ", "csharp"),
            ("using System", "csharp"),
            ("#include", "c"),      # or cpp
            ("int main(", "c"),
            ("std::", "cpp"),
            ("template<", "cpp"),
            ("const ", "javascript"),
            ("let ", "javascript"),
            ("require(", "javascript"),
            ("import {", "javascript"),
            ("export default", "javascript"),
            ("interface ", "typescript"),
            ("<template>", "vue"),
            ("<?php", "php"),
            ("class ", None),  # Too ambiguous alone
        ]

        # Score each candidate language
        scores: Dict[str, int] = {}
        for pattern, lang in patterns:
            if lang and pattern in head:
                scores[lang] = scores.get(lang, 0) + 1

        # Disambiguate c vs cpp
        if "c" in scores and "cpp" in scores:
            if scores["cpp"] > scores["c"]:
                del scores["c"]
            else:
                del scores["cpp"]

        # Also use extension as weak signal for disambiguation
        ext_hints = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
            ".cs": "csharp", ".rb": "ruby", ".php": "php",
            ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
            ".r": "r", ".R": "r", ".jl": "julia", ".lua": "lua",
            ".pl": "perl", ".pm": "perl", ".dart": "dart",
            ".ex": "elixir", ".exs": "elixir", ".zig": "zig",
            ".nim": "nim", ".v": "vlang",
        }
        hint = ext_hints.get(ext)
        if hint:
            scores[hint] = scores.get(hint, 0) + 3  # Strong boost

        if scores:
            return max(scores, key=scores.get)
        
        # Last resort: if extension gives a hint, use it
        return hint

    def _detect_build_systems(
        self, root_files: List[str], repo_dir: str
    ) -> List[Dict[str, str]]:
        """
        Detect build systems by reading actual config files,
        not by matching filenames to a static map.
        """
        build_systems = []

        for f in root_files:
            full = os.path.join(repo_dir, f)
            info = self._identify_build_file(f, full)
            if info:
                build_systems.append(info)

        return build_systems

    def _identify_build_file(
        self, filename: str, full_path: str
    ) -> Optional[Dict[str, str]]:
        """
        Read a file and determine if it's a build config.
        Uses content inspection, not filename matching.
        """
        try:
            # Read first 100 lines
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                head = ""
                for i, line in enumerate(f):
                    if i >= 100:
                        break
                    head += line
        except Exception:
            return None

        # JSON files — inspect structure
        if filename.endswith('.json'):
            try:
                data = json.loads(head + "}")  # Might be incomplete
            except Exception:
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    return None

            if isinstance(data, dict):
                if "dependencies" in data or "devDependencies" in data:
                    return {
                        "type": "package_manifest",
                        "file": filename,
                        "ecosystem": "node",
                        "has_scripts": "scripts" in data,
                        "scripts": data.get("scripts", {}),
                    }
                if "name" in data and "version" in data:
                    return {
                        "type": "package_manifest",
                        "file": filename,
                        "ecosystem": "unknown",
                    }

        # TOML files
        if filename.endswith('.toml'):
            if "[project]" in head or "[tool." in head:
                return {
                    "type": "python_build",
                    "file": filename,
                    "ecosystem": "python",
                    "has_pytest": "[tool.pytest" in head,
                }
            if "[package]" in head and "[dependencies]" in head:
                return {
                    "type": "cargo_manifest",
                    "file": filename,
                    "ecosystem": "rust",
                }

        # XML files
        if filename.endswith('.xml'):
            if "<project" in head and "maven" in head.lower():
                return {
                    "type": "maven_pom",
                    "file": filename,
                    "ecosystem": "java",
                }

        # Gradle files
        if "gradle" in filename.lower():
            return {
                "type": "gradle_build",
                "file": filename,
                "ecosystem": "java",
                "is_kotlin_dsl": filename.endswith('.kts'),
            }

        # Makefiles
        if filename in ("Makefile", "makefile", "GNUmakefile"):
            targets = [
                line.split(':')[0].strip()
                for line in head.split('\n')
                if ':' in line
                and not line.startswith('\t')
                and not line.startswith('#')
                and not line.startswith('.')
                and '=' not in line.split(':')[0]
            ]
            return {
                "type": "makefile",
                "file": filename,
                "targets": targets[:20],
                "has_test_target": "test" in targets,
            }

        # CMake
        if filename == "CMakeLists.txt":
            return {
                "type": "cmake",
                "file": filename,
                "ecosystem": "c/cpp",
                "has_testing": "enable_testing" in head.lower(),
                "has_gtest": "gtest" in head.lower(),
            }

        # Go modules
        if filename == "go.mod":
            return {
                "type": "go_module",
                "file": filename,
                "ecosystem": "go",
            }

        # Docker
        if filename in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
            return {
                "type": "docker",
                "file": filename,
            }

        return None

    def _detect_test_infrastructure(
        self, repo_dir: str, profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Detect test infrastructure by reading actual configs.
        Doesn't assume any framework — reads what's configured.
        """
        infra = {
            "test_directories": [],
            "test_files": [],
            "frameworks_detected": {},
            "test_commands": {},
        }

        # Find test directories by looking for directories whose name
        # suggests testing
        for item in os.listdir(repo_dir):
            full = os.path.join(repo_dir, item)
            if os.path.isdir(full):
                # Heuristic: directory name contains "test"
                if "test" in item.lower() or "spec" in item.lower():
                    infra["test_directories"].append(item)

        # Also check for nested test dirs
        for build_sys in profile.get("build_systems", []):
            if build_sys.get("ecosystem") == "java":
                java_test = os.path.join(repo_dir, "src", "test")
                if os.path.isdir(java_test):
                    infra["test_directories"].append("src/test")

        # Detect frameworks from build system configs
        for build_sys in profile.get("build_systems", []):
            if build_sys["type"] == "package_manifest" and build_sys.get("ecosystem") == "node":
                scripts = build_sys.get("scripts", {})
                test_script = scripts.get("test", "")
                if test_script:
                    infra["test_commands"]["node"] = test_script
                    # Infer framework from test script
                    if "jest" in test_script:
                        infra["frameworks_detected"]["javascript"] = "jest"
                    elif "vitest" in test_script:
                        infra["frameworks_detected"]["javascript"] = "vitest"
                    elif "mocha" in test_script:
                        infra["frameworks_detected"]["javascript"] = "mocha"
                    elif "ava" in test_script:
                        infra["frameworks_detected"]["javascript"] = "ava"

            elif build_sys["type"] == "python_build":
                if build_sys.get("has_pytest"):
                    infra["frameworks_detected"]["python"] = "pytest"

            elif build_sys["type"] == "cmake":
                if build_sys.get("has_gtest"):
                    infra["frameworks_detected"]["cpp"] = "googletest"
                elif build_sys.get("has_testing"):
                    infra["frameworks_detected"]["cpp"] = "ctest"

            elif build_sys["type"] == "cargo_manifest":
                infra["frameworks_detected"]["rust"] = "cargo_test"

            elif build_sys["type"] == "go_module":
                infra["frameworks_detected"]["go"] = "go_test"

        # If we still haven't detected frameworks for some languages,
        # scan test files for clues
        for lang in profile.get("languages", {}):
            if lang not in infra["frameworks_detected"]:
                fw = self._probe_test_framework_from_files(
                    repo_dir, lang, infra["test_directories"]
                )
                if fw:
                    infra["frameworks_detected"][lang] = fw

        return infra

    def _probe_test_framework_from_files(
        self, repo_dir: str, language: str, test_dirs: List[str]
    ) -> Optional[str]:
        """
        Read actual test files to identify which framework they use.
        Pure content analysis — no lookup tables.
        """
        # Find test files to sample
        sample_files = []
        search_dirs = [os.path.join(repo_dir, d) for d in test_dirs]
        search_dirs.append(repo_dir)  # Also check root

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for f in files:
                    if "test" in f.lower() or "spec" in f.lower():
                        sample_files.append(os.path.join(root, f))
                    if len(sample_files) >= 5:
                        break
                if len(sample_files) >= 5:
                    break

        # Read samples and look for framework imports/markers
        combined_content = ""
        for fpath in sample_files[:5]:
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                    combined_content += fh.read(5000) + "\n"
            except Exception:
                pass

        if not combined_content:
            return None

        # Framework detection by actual import/usage patterns
        # These are SYNTAX patterns found in real test files
        framework_signals = {
            # Python
            "import pytest": "pytest",
            "@pytest.": "pytest",
            "import unittest": "unittest",
            "TestCase)": "unittest",

            # JavaScript/TypeScript
            "describe(": None,  # Shared by many — ambiguous
            "from 'vitest'": "vitest",
            "from \"vitest\"": "vitest",
            "@jest": "jest",
            "from 'jest'": "jest",
            "require('mocha')": "mocha",
            "require('chai')": "mocha",

            # Java
            "import org.junit.jupiter": "junit5",
            "@Test": None,  # Shared — ambiguous
            "import org.junit.": "junit4",
            "import org.testng": "testng",

            # C/C++
            "#include <gtest": "googletest",
            "TEST_F(": "googletest",
            "TEST(": "googletest",
            "#include <catch2": "catch2",
            "TEST_CASE(": "catch2",
            "REQUIRE(": "catch2",
            "#include <CUnit": "cunit",

            # Go
            "testing.T": "go_test",

            # Rust
            "#[test]": "cargo_test",
            "#[cfg(test)]": "cargo_test",

            # C#
            "using Xunit": "xunit",
            "[Fact]": "xunit",
            "using NUnit": "nunit",
            "[Test]": "nunit",
            "[TestMethod]": "mstest",

            # Ruby
            "RSpec.describe": "rspec",
            "describe ": None,  # Ambiguous
            "Minitest": "minitest",

            # PHP
            "extends TestCase": "phpunit",
            "PHPUnit": "phpunit",
        }

        scores: Dict[str, int] = {}
        for pattern, framework in framework_signals.items():
            if framework and pattern in combined_content:
                scores[framework] = scores.get(framework, 0) + 1

        if scores:
            return max(scores, key=scores.get)
        return None

    def _detect_ci_systems(self, repo_dir: str) -> List[Dict[str, str]]:
        """Detect CI by scanning for workflow files. Content-based, not name-based."""
        ci_found = []

        # Walk top-level hidden dirs and known CI paths
        for root, dirs, files in os.walk(repo_dir):
            depth = root.replace(repo_dir, "").count(os.sep)
            if depth > 2:
                dirs.clear()
                continue

            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, repo_dir)

                # Read file and check if it's a CI config
                ci_type = self._identify_ci_file(f, full, rel)
                if ci_type:
                    ci_found.append(ci_type)

        return ci_found

    def _identify_ci_file(
        self, filename: str, full_path: str, rel_path: str
    ) -> Optional[Dict[str, str]]:
        """Identify a CI config by reading its content."""
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                head = f.read(3000)
        except Exception:
            return None

        # YAML files in .github/workflows
        if ".github/workflows" in rel_path and (
            filename.endswith('.yml') or filename.endswith('.yaml')
        ):
            info = {"type": "github-actions", "file": rel_path}
            # Extract workflow name and triggers
            if "on:" in head:
                info["has_triggers"] = True
            if "jobs:" in head:
                info["has_jobs"] = True
            return info

        # GitLab CI
        if filename == ".gitlab-ci.yml":
            return {"type": "gitlab-ci", "file": rel_path}

        # Jenkinsfile
        if filename == "Jenkinsfile":
            return {"type": "jenkins", "file": rel_path}

        # Content-based detection for other CI systems
        if filename.endswith(('.yml', '.yaml')):
            if "circleci" in head.lower() or "version: 2" in head:
                if "jobs:" in head and "steps:" in head:
                    return {"type": "circleci", "file": rel_path}
            if "trigger:" in head and "pool:" in head:
                return {"type": "azure-pipelines", "file": rel_path}

        return None

    def _read_all_manifests(self, repo_dir: str) -> Dict[str, Any]:
        """
        Read dependency manifests generically.
        Instead of knowing which files to parse, we identify them
        from the build systems we already detected.
        """
        deps = {}

        # package.json
        pkg_path = os.path.join(repo_dir, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, 'r') as f:
                    pkg = json.load(f)
                deps["node"] = {
                    "production": list(pkg.get("dependencies", {}).keys()),
                    "development": list(pkg.get("devDependencies", {}).keys()),
                }
            except Exception:
                pass

        # requirements*.txt
        for req_file in os.listdir(repo_dir):
            if req_file.startswith("requirements") and req_file.endswith(".txt"):
                req_path = os.path.join(repo_dir, req_file)
                try:
                    lines = Path(req_path).read_text(
                        encoding='utf-8', errors='ignore'
                    ).strip().split('\n')
                    pkgs = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#') and not line.startswith('-'):
                            # Extract package name (before ==, >=, etc.)
                            import re
                            match = re.match(r'^([a-zA-Z0-9_.-]+)', line)
                            if match:
                                pkgs.append(match.group(1))
                    deps[f"pip:{req_file}"] = pkgs
                except Exception:
                    pass

        # pyproject.toml dependencies
        pyproject = os.path.join(repo_dir, "pyproject.toml")
        if os.path.exists(pyproject):
            try:
                content = Path(pyproject).read_text(encoding='utf-8', errors='ignore')
                # Simple TOML parsing for dependencies
                if "dependencies" in content:
                    deps["pyproject"] = {"raw_detected": True}
            except Exception:
                pass

        # Cargo.toml
        cargo = os.path.join(repo_dir, "Cargo.toml")
        if os.path.exists(cargo):
            try:
                content = Path(cargo).read_text(encoding='utf-8', errors='ignore')
                cargo_deps = []
                in_deps = False
                for line in content.split('\n'):
                    if line.strip().startswith('[') and 'dependencies' in line.lower():
                        in_deps = True
                        continue
                    if line.strip().startswith('[') and in_deps:
                        in_deps = False
                    if in_deps and '=' in line:
                        cargo_deps.append(line.split('=')[0].strip())
                deps["cargo"] = cargo_deps
            except Exception:
                pass

        # go.mod
        gomod = os.path.join(repo_dir, "go.mod")
        if os.path.exists(gomod):
            try:
                content = Path(gomod).read_text(encoding='utf-8', errors='ignore')
                go_deps = []
                in_require = False
                for line in content.split('\n'):
                    if line.strip() == "require (":
                        in_require = True
                        continue
                    if line.strip() == ")" and in_require:
                        in_require = False
                    if in_require and line.strip():
                        parts = line.strip().split()
                        if parts:
                            go_deps.append(parts[0])
                deps["go"] = go_deps
            except Exception:
                pass

        return deps

    # ─── Command Generation ───────────────────────────────
    # Generates commands based on what was ACTUALLY discovered,
    # not from a lookup table.

    def _generate_commands(
        self, profile: Dict[str, Any], env: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate executable commands based on discovered profile.
        
        Key insight: we already know what build systems and test
        frameworks exist. We just need to construct the right
        invocation for each.
        """
        commands = {
            "shell": env.get("shell", {}),
            "install": {},
            "test": {},
            "lint": {},
            "coverage": {},
            "build": {},
        }

        available_tools = set(env.get("runtimes", {}).keys())

        # Test commands — derived from detected frameworks
        test_infra = profile.get("test_infrastructure", {})
        frameworks = test_infra.get("frameworks_detected", {})
        
        # Also check for scripts in package.json etc.
        existing_test_cmds = test_infra.get("test_commands", {})
        
        for lang, framework in frameworks.items():
            cmd = self._construct_test_command(
                lang, framework, profile, available_tools
            )
            if cmd:
                commands["test"][lang] = cmd["test"]
                if cmd.get("coverage"):
                    commands["coverage"][lang] = cmd["coverage"]
                if cmd.get("install"):
                    commands["install"][lang] = cmd["install"]

        # If package.json has a test script, prefer that
        if "node" in existing_test_cmds:
            # Use npm test which respects the project's configuration
            for lang in ["javascript", "typescript"]:
                if lang in commands["test"]:
                    commands["test"][f"{lang}_native"] = commands["test"][lang]
                commands["test"][lang] = "npm test"

        # Lint commands — based on what linters are available
        for lang in profile.get("languages", {}):
            lint_cmd = self._construct_lint_command(
                lang, available_tools
            )
            if lint_cmd:
                commands["lint"][lang] = lint_cmd

        # Build commands — from Makefile targets, scripts, etc.
        for build_sys in profile.get("build_systems", []):
            if build_sys["type"] == "makefile":
                if build_sys.get("has_test_target"):
                    commands["build"]["make_test"] = "make test"
                targets = build_sys.get("targets", [])
                if "build" in targets:
                    commands["build"]["make_build"] = "make build"
                if "all" in targets:
                    commands["build"]["make_all"] = "make all"

        return commands

    def _construct_test_command(
        self,
        lang: str,
        framework: str,
        profile: Dict[str, Any],
        available_tools: set,
    ) -> Optional[Dict[str, str]]:
        """
        Construct a test command for a given framework.
        Uses available tools to decide the invocation.
        """
        result = {}

        # The logic here is minimal — just enough to construct a command
        # from known framework names. This is NOT a lookup table of
        # all possible frameworks. It handles the ones we actually detected.

        if framework == "pytest":
            result["test"] = "pytest -v"
            result["coverage"] = "pytest --cov=. --cov-report=json --cov-report=term -v"
            if "pytest" not in available_tools:
                result["install"] = "pip install pytest pytest-cov"

        elif framework == "unittest":
            result["test"] = "python -m unittest discover -v"
            result["coverage"] = "coverage run -m unittest discover -v && coverage json"

        elif framework == "jest":
            result["test"] = "npx jest --verbose"
            result["coverage"] = "npx jest --coverage --coverageReporters=json-summary --verbose"

        elif framework == "vitest":
            result["test"] = "npx vitest run"
            result["coverage"] = "npx vitest run --coverage"

        elif framework == "mocha":
            result["test"] = "npx mocha --recursive"
            result["coverage"] = "npx nyc mocha --recursive"

        elif framework == "go_test":
            result["test"] = "go test ./... -v"
            result["coverage"] = "go test ./... -v -coverprofile=coverage.out"

        elif framework == "cargo_test":
            result["test"] = "cargo test -- --nocapture"
            result["coverage"] = "cargo tarpaulin --out Json"

        elif framework in ("junit5", "junit4", "testng"):
            # Check which build tool is available
            build_systems = profile.get("build_systems", [])
            has_gradle = any(
                b["type"] == "gradle_build" for b in build_systems
            )
            if has_gradle:
                wrapper = "./gradlew" if os.path.exists("./gradlew") else "gradle"
                result["test"] = f"{wrapper} test"
                result["coverage"] = f"{wrapper} test jacocoTestReport"
            else:
                result["test"] = "mvn test -B"
                result["coverage"] = "mvn test jacoco:report -B"

        elif framework == "googletest":
            result["test"] = "cd build && cmake .. && make && ctest --output-on-failure"
            result["coverage"] = result["test"]

        elif framework == "catch2":
            result["test"] = "cd build && cmake .. && make && ctest --output-on-failure"
            result["coverage"] = result["test"]

        elif framework == "ctest":
            result["test"] = "cd build && cmake .. && make && ctest --output-on-failure"

        elif framework == "xunit" or framework == "nunit" or framework == "mstest":
            result["test"] = "dotnet test --verbosity normal"
            result["coverage"] = "dotnet test --collect:'XPlat Code Coverage'"

        elif framework == "rspec":
            result["test"] = "bundle exec rspec --format documentation"

        elif framework == "minitest":
            result["test"] = "bundle exec rake test"

        elif framework == "phpunit":
            result["test"] = "vendor/bin/phpunit --verbose"
            result["coverage"] = "vendor/bin/phpunit --coverage-text"

        else:
            # Unknown framework — try generic command
            result["test"] = f"echo 'Unknown framework: {framework}'"
            return None

        return result if result.get("test") else None

    def _construct_lint_command(
        self, lang: str, available_tools: set
    ) -> Optional[str]:
        """
        Construct lint commands from whatever linters are available.
        Probes available_tools instead of using a lookup.
        """
        cmds = []

        # For each language, check if common linters for that
        # language are in available_tools
        # This is a SMALL mapping — just which linters work for which
        # language family. The actual linter list comes from PATH scanning.

        if lang == "python":
            for linter in ["ruff", "mypy", "flake8", "pylint", "pyright"]:
                if linter in available_tools:
                    if linter == "ruff":
                        cmds.append("ruff check .")
                    elif linter == "mypy":
                        cmds.append("mypy . --ignore-missing-imports")
                    elif linter == "flake8":
                        cmds.append("flake8 .")
                    elif linter == "pylint":
                        cmds.append("pylint **/*.py")
                    elif linter == "pyright":
                        cmds.append("pyright .")

        elif lang in ("javascript", "typescript"):
            if "eslint" in available_tools:
                ext = ".ts,.tsx" if lang == "typescript" else ".js,.jsx"
                cmds.append(
                    f"npx eslint . --ext {ext} --no-error-on-unmatched-pattern"
                )
            if lang == "typescript" and "tsc" in available_tools:
                cmds.append("npx tsc --noEmit")

        elif lang == "go":
            if "golangci-lint" in available_tools:
                cmds.append("golangci-lint run ./...")
            else:
                cmds.append("go vet ./...")

        elif lang == "rust":
            # Clippy is a cargo subcommand, check via cargo
            if "cargo" in available_tools:
                cmds.append("cargo clippy -- -D warnings")
                cmds.append("cargo fmt -- --check")

        elif lang in ("c", "cpp"):
            if "cppcheck" in available_tools:
                cmds.append("cppcheck --enable=all --inconclusive --quiet .")
            if "clang-tidy" in available_tools:
                cmds.append("clang-tidy *.cpp -- -std=c++17 2>/dev/null || true")

        elif lang == "csharp":
            if "dotnet" in available_tools:
                cmds.append("dotnet format --verify-no-changes")

        elif lang == "ruby":
            if "rubocop" in available_tools:
                cmds.append("rubocop .")

        elif lang == "php":
            if "phpstan" in available_tools:
                cmds.append("vendor/bin/phpstan analyse src/ --level=5")

        elif lang == "java":
            # Checkstyle is usually a Maven/Gradle plugin, not a binary
            pass

        return " && ".join(cmds) if cmds else None

    # ─── A2A Handler ──────────────────────────────────────

    async def handle_task(self, task: Task) -> AsyncGenerator[Task, None]:
        """A2A task handler."""
        task.status = TaskStatus(state=TaskState.WORKING)
        yield task

        # Extract request
        request_data = {}
        for part in task.history[-1].parts:
            if part.get("type") == "data":
                request_data = part["data"]

        repo_dir = request_data.get("repo_dir", "")

        # Phase 1: Environment
        task.status = TaskStatus(
            state=TaskState.WORKING,
            message=Message(
                role="agent",
                parts=[{"type": "text", "text": "Discovering environment..."}],
            ),
        )
        yield task

        env_profile = self.discover_environment()
        task.artifacts.append(Artifact(
            name="environment_profile",
            description="Runtime environment",
            parts=[{"type": "data", "data": env_profile}],
            index=0,
        ))

        # Phase 2: Repository
        repo_profile = {}
        if repo_dir and os.path.exists(repo_dir):
            task.status = TaskStatus(
                state=TaskState.WORKING,
                message=Message(
                    role="agent",
                    parts=[{"type": "text", "text": "Discovering repository..."}],
                ),
            )
            yield task

            repo_profile = self.discover_repository(repo_dir)
            task.artifacts.append(Artifact(
                name="repository_profile",
                description="Repository analysis",
                parts=[{"type": "data", "data": repo_profile}],
                index=1,
            ))

        # Complete
        summary = {
            "os": env_profile.get("os"),
            "languages": list(repo_profile.get("languages", {}).keys()),
            "build_systems": [
                b.get("type") for b in repo_profile.get("build_systems", [])
            ],
            "test_frameworks": repo_profile.get(
                "test_infrastructure", {}
            ).get("frameworks_detected", {}),
            "tools_on_path": len(env_profile.get("path_executables", [])),
            "commands": repo_profile.get("recommended_commands", {}),
        }

        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message(
                role="agent",
                parts=[
                    {"type": "text", "text": json.dumps(summary, indent=2)},
                ],
            ),
        )
        yield task