"""Multi-language project detection for the QA pipeline tools."""
import os
import json
from typing import Dict, List, Optional, Any


class ProjectProfile:
    """Detected project profile with languages, frameworks, and tools."""

    def __init__(self):
        self.languages: List[str] = []
        self.build_systems: List[str] = []
        self.test_frameworks: Dict[str, List[str]] = {}
        self.linters: Dict[str, List[str]] = {}
        self.coverage_tools: Dict[str, List[str]] = {}
        self.test_commands: Dict[str, str] = {}
        self.lint_commands: Dict[str, str] = {}
        self.coverage_commands: Dict[str, str] = {}
        self.install_commands: Dict[str, str] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "languages": self.languages,
            "build_systems": self.build_systems,
            "test_frameworks": self.test_frameworks,
            "linters": self.linters,
            "coverage_tools": self.coverage_tools,
            "test_commands": self.test_commands,
            "lint_commands": self.lint_commands,
            "coverage_commands": self.coverage_commands,
            "install_commands": self.install_commands,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ── Language Detection Signatures ─────────────────────────

LANGUAGE_SIGNATURES = {
    "python": {
        "extensions": [".py"],
        "config_files": [
            "setup.py", "setup.cfg", "pyproject.toml",
            "requirements.txt", "Pipfile", "poetry.lock",
            "tox.ini", "pytest.ini", ".flake8"
        ],
        "markers": ["__init__.py", "__main__.py"],
    },
    "javascript": {
        "extensions": [".js", ".mjs", ".cjs", ".jsx"],
        "config_files": [
            "package.json", ".eslintrc.js", ".eslintrc.json",
            ".babelrc", "webpack.config.js", "rollup.config.js"
        ],
        "markers": ["node_modules"],
    },
    "typescript": {
        "extensions": [".ts", ".tsx"],
        "config_files": ["tsconfig.json", "tsconfig.build.json"],
        "markers": [],
    },
    "java": {
        "extensions": [".java"],
        "config_files": [
            "pom.xml", "build.gradle", "build.gradle.kts",
            "settings.gradle", "gradlew"
        ],
        "markers": ["src/main/java", "src/test/java"],
    },
    "c": {
        "extensions": [".c", ".h"],
        "config_files": ["Makefile", "CMakeLists.txt", "configure.ac", "meson.build"],
        "markers": [],
    },
    "cpp": {
        "extensions": [".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"],
        "config_files": ["CMakeLists.txt", "Makefile", "meson.build", "conanfile.txt", "vcpkg.json"],
        "markers": [],
    },
    "csharp": {
        "extensions": [".cs"],
        "config_files": ["*.csproj", "*.sln", "Directory.Build.props", "global.json"],
        "markers": ["bin", "obj"],
    },
    "go": {
        "extensions": [".go"],
        "config_files": ["go.mod", "go.sum"],
        "markers": [],
    },
    "rust": {
        "extensions": [".rs"],
        "config_files": ["Cargo.toml", "Cargo.lock"],
        "markers": ["src/main.rs", "src/lib.rs"],
    },
    "ruby": {
        "extensions": [".rb"],
        "config_files": ["Gemfile", "Gemfile.lock", "Rakefile", ".rubocop.yml"],
        "markers": [],
    },
    "php": {
        "extensions": [".php"],
        "config_files": ["composer.json", "composer.lock", "phpunit.xml"],
        "markers": [],
    },
    "swift": {
        "extensions": [".swift"],
        "config_files": ["Package.swift", "*.xcodeproj"],
        "markers": [],
    },
    "kotlin": {
        "extensions": [".kt", ".kts"],
        "config_files": ["build.gradle.kts"],
        "markers": [],
    },
}


# ── Test Framework Detection ──────────────────────────────

TEST_FRAMEWORK_DETECTION = {
    "python": {
        "detect_in_files": ["requirements.txt", "setup.cfg", "pyproject.toml", "tox.ini", "Pipfile"],
        "detect_in_dirs": ["tests", "test"],
        "frameworks": {
            "pytest": {
                "markers": ["pytest", "conftest.py", "pytest.ini", "[tool.pytest"],
                "install": "pip install pytest pytest-cov",
                "test_cmd": "pytest -v",
                "coverage_cmd": "pytest --cov=. --cov-report=json --cov-report=term -v",
                "coverage_tool": "pytest-cov",
            },
            "unittest": {
                "markers": ["unittest", "import unittest"],
                "install": "",
                "test_cmd": "python -m unittest discover -v",
                "coverage_cmd": "coverage run -m unittest discover -v && coverage json",
                "coverage_tool": "coverage",
            },
            "nose2": {
                "markers": ["nose2"],
                "install": "pip install nose2",
                "test_cmd": "nose2 -v",
                "coverage_cmd": "nose2 --with-coverage -v",
                "coverage_tool": "coverage",
            },
        },
        "default_framework": "pytest",
        "linters": {
            "ruff": {"install": "pip install ruff", "cmd": "ruff check ."},
            "mypy": {"install": "pip install mypy", "cmd": "mypy . --ignore-missing-imports"},
        },
    },
    "javascript": {
        "detect_in_files": ["package.json"],
        "detect_in_dirs": ["__tests__", "test", "tests", "spec"],
        "frameworks": {
            "jest": {
                "markers": ["jest", "@jest", "jest.config"],
                "install": "npm install --save-dev jest",
                "test_cmd": "npx jest --verbose",
                "coverage_cmd": "npx jest --coverage --coverageReporters=json-summary --verbose",
                "coverage_tool": "jest --coverage",
            },
            "vitest": {
                "markers": ["vitest", "@vitest"],
                "install": "npm install --save-dev vitest @vitest/coverage-v8",
                "test_cmd": "npx vitest run",
                "coverage_cmd": "npx vitest run --coverage",
                "coverage_tool": "@vitest/coverage-v8",
            },
            "mocha": {
                "markers": ["mocha", ".mocharc"],
                "install": "npm install --save-dev mocha chai nyc",
                "test_cmd": "npx mocha --recursive",
                "coverage_cmd": "npx nyc mocha --recursive",
                "coverage_tool": "nyc",
            },
        },
        "default_framework": "jest",
        "linters": {
            "eslint": {"install": "npm install --save-dev eslint", "cmd": "npx eslint . --ext .js,.jsx --no-error-on-unmatched-pattern"},
        },
    },
    "typescript": {
        "detect_in_files": ["package.json", "tsconfig.json"],
        "detect_in_dirs": ["__tests__", "test", "tests", "spec"],
        "frameworks": {
            "jest": {
                "markers": ["jest", "ts-jest", "@jest"],
                "install": "npm install --save-dev jest ts-jest @types/jest",
                "test_cmd": "npx jest --verbose",
                "coverage_cmd": "npx jest --coverage --coverageReporters=json-summary --verbose",
                "coverage_tool": "jest --coverage",
            },
            "vitest": {
                "markers": ["vitest"],
                "install": "npm install --save-dev vitest @vitest/coverage-v8",
                "test_cmd": "npx vitest run",
                "coverage_cmd": "npx vitest run --coverage",
                "coverage_tool": "@vitest/coverage-v8",
            },
        },
        "default_framework": "jest",
        "linters": {
            "eslint": {"install": "npm install --save-dev eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin", "cmd": "npx eslint . --ext .ts,.tsx --no-error-on-unmatched-pattern"},
            "tsc": {"install": "", "cmd": "npx tsc --noEmit"},
        },
    },
    "java": {
        "detect_in_files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "detect_in_dirs": ["src/test/java"],
        "frameworks": {
            "junit5": {
                "markers": ["junit-jupiter", "org.junit.jupiter", "@Test"],
                "install": "",
                "test_cmd": "mvn test -B",
                "coverage_cmd": "mvn test jacoco:report -B",
                "coverage_tool": "JaCoCo",
            },
            "testng": {
                "markers": ["testng", "org.testng"],
                "install": "",
                "test_cmd": "mvn test -B",
                "coverage_cmd": "mvn test jacoco:report -B",
                "coverage_tool": "JaCoCo",
            },
        },
        "default_framework": "junit5",
        "linters": {
            "checkstyle": {"install": "", "cmd": "mvn checkstyle:check -B"},
        },
    },
    "c": {
        "detect_in_files": ["Makefile", "CMakeLists.txt", "configure.ac", "meson.build"],
        "detect_in_dirs": ["tests", "test"],
        "frameworks": {
            "cunit": {
                "markers": ["CUnit", "cunit.h", "CU_"],
                "install": "sudo apt-get install -y libcunit1-dev || brew install cunit",
                "test_cmd": "make test || ctest --output-on-failure",
                "coverage_cmd": "make test && gcov *.c",
                "coverage_tool": "gcov/lcov",
            },
            "check": {
                "markers": ["check.h", "ck_assert", "START_TEST"],
                "install": "sudo apt-get install -y check || brew install check",
                "test_cmd": "make test || ctest --output-on-failure",
                "coverage_cmd": "make test && gcov *.c",
                "coverage_tool": "gcov/lcov",
            },
            "cmake_ctest": {
                "markers": ["enable_testing", "add_test", "ctest"],
                "install": "",
                "test_cmd": "cd build && cmake .. && make && ctest --output-on-failure",
                "coverage_cmd": "cd build && cmake -DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_FLAGS='--coverage' .. && make && ctest --output-on-failure && gcov *.c",
                "coverage_tool": "gcov/lcov",
            },
        },
        "default_framework": "cmake_ctest",
        "linters": {
            "cppcheck": {"install": "sudo apt-get install -y cppcheck || brew install cppcheck", "cmd": "cppcheck --enable=all --inconclusive --quiet ."},
        },
    },
    "cpp": {
        "detect_in_files": ["CMakeLists.txt", "Makefile", "meson.build"],
        "detect_in_dirs": ["tests", "test"],
        "frameworks": {
            "googletest": {
                "markers": ["gtest", "googletest", "TEST_F", "TEST(", "EXPECT_", "ASSERT_"],
                "install": "sudo apt-get install -y libgtest-dev || brew install googletest",
                "test_cmd": "cd build && cmake .. && make && ctest --output-on-failure",
                "coverage_cmd": "cd build && cmake -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='--coverage' .. && make && ctest --output-on-failure && gcov *.cpp",
                "coverage_tool": "gcov/lcov",
            },
            "catch2": {
                "markers": ["catch2", "Catch.hpp", "CATCH_", "TEST_CASE", "SECTION", "REQUIRE"],
                "install": "sudo apt-get install -y catch2 || brew install catch2",
                "test_cmd": "cd build && cmake .. && make && ctest --output-on-failure",
                "coverage_cmd": "cd build && cmake -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='--coverage' .. && make && ctest --output-on-failure",
                "coverage_tool": "gcov/lcov",
            },
        },
        "default_framework": "googletest",
        "linters": {
            "cppcheck": {"install": "sudo apt-get install -y cppcheck || brew install cppcheck", "cmd": "cppcheck --enable=all --inconclusive --quiet --language=c++ ."},
            "clang-tidy": {"install": "sudo apt-get install -y clang-tidy || brew install llvm", "cmd": "clang-tidy *.cpp -- -std=c++17"},
        },
    },
    "csharp": {
        "detect_in_files": ["*.csproj", "*.sln"],
        "detect_in_dirs": [],
        "frameworks": {
            "xunit": {
                "markers": ["xunit", "Xunit", "[Fact]", "[Theory]"],
                "install": "dotnet add package xunit xunit.runner.visualstudio",
                "test_cmd": "dotnet test --verbosity normal",
                "coverage_cmd": "dotnet test --collect:'XPlat Code Coverage' --verbosity normal",
                "coverage_tool": "coverlet",
            },
            "nunit": {
                "markers": ["nunit", "NUnit", "[Test]", "[TestCase]"],
                "install": "dotnet add package NUnit NUnit3TestAdapter",
                "test_cmd": "dotnet test --verbosity normal",
                "coverage_cmd": "dotnet test --collect:'XPlat Code Coverage' --verbosity normal",
                "coverage_tool": "coverlet",
            },
            "mstest": {
                "markers": ["MSTest", "[TestMethod]", "[TestClass]"],
                "install": "",
                "test_cmd": "dotnet test --verbosity normal",
                "coverage_cmd": "dotnet test --collect:'XPlat Code Coverage' --verbosity normal",
                "coverage_tool": "coverlet",
            },
        },
        "default_framework": "xunit",
        "linters": {
            "dotnet-format": {"install": "", "cmd": "dotnet format --verify-no-changes"},
        },
    },
    "go": {
        "detect_in_files": ["go.mod", "go.sum"],
        "detect_in_dirs": [],
        "frameworks": {
            "go_test": {
                "markers": ["_test.go", "testing.T", "func Test"],
                "install": "",
                "test_cmd": "go test ./... -v",
                "coverage_cmd": "go test ./... -v -coverprofile=coverage.out && go tool cover -func=coverage.out",
                "coverage_tool": "go test -cover",
            },
        },
        "default_framework": "go_test",
        "linters": {
            "golangci-lint": {"install": "go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest", "cmd": "golangci-lint run ./..."},
            "go-vet": {"install": "", "cmd": "go vet ./..."},
        },
    },
    "rust": {
        "detect_in_files": ["Cargo.toml", "Cargo.lock"],
        "detect_in_dirs": ["tests"],
        "frameworks": {
            "cargo_test": {
                "markers": ["#[test]", "#[cfg(test)]", "mod tests"],
                "install": "",
                "test_cmd": "cargo test -- --nocapture",
                "coverage_cmd": "cargo install cargo-tarpaulin && cargo tarpaulin --out Json",
                "coverage_tool": "cargo-tarpaulin",
            },
        },
        "default_framework": "cargo_test",
        "linters": {
            "clippy": {"install": "rustup component add clippy", "cmd": "cargo clippy -- -D warnings"},
            "rustfmt": {"install": "rustup component add rustfmt", "cmd": "cargo fmt -- --check"},
        },
    },
    "ruby": {
        "detect_in_files": ["Gemfile", "Rakefile", ".rubocop.yml"],
        "detect_in_dirs": ["spec", "test"],
        "frameworks": {
            "rspec": {
                "markers": ["rspec", "describe", "it ", "expect("],
                "install": "gem install rspec",
                "test_cmd": "rspec --format documentation",
                "coverage_cmd": "rspec --format documentation",
                "coverage_tool": "simplecov",
            },
            "minitest": {
                "markers": ["minitest", "Minitest", "def test_"],
                "install": "",
                "test_cmd": "ruby -Ilib -Itest -e 'Dir.glob(\"test/**/*_test.rb\").each{|f| require \"./#{f}\"}'",
                "coverage_cmd": "ruby -Ilib -Itest -e 'Dir.glob(\"test/**/*_test.rb\").each{|f| require \"./#{f}\"}'",
                "coverage_tool": "simplecov",
            },
        },
        "default_framework": "rspec",
        "linters": {
            "rubocop": {"install": "gem install rubocop", "cmd": "rubocop ."},
        },
    },
    "php": {
        "detect_in_files": ["composer.json", "phpunit.xml", "phpunit.xml.dist"],
        "detect_in_dirs": ["tests", "test"],
        "frameworks": {
            "phpunit": {
                "markers": ["phpunit", "PHPUnit", "extends TestCase"],
                "install": "composer require --dev phpunit/phpunit",
                "test_cmd": "vendor/bin/phpunit --verbose",
                "coverage_cmd": "vendor/bin/phpunit --coverage-text --coverage-clover=coverage.xml",
                "coverage_tool": "phpunit --coverage",
            },
        },
        "default_framework": "phpunit",
        "linters": {
            "phpstan": {"install": "composer require --dev phpstan/phpstan", "cmd": "vendor/bin/phpstan analyse src/ --level=5"},
        },
    },
}


def detect_languages(repo_dir: str) -> List[str]:
    """Detect programming languages present in the repository."""
    detected = []
    if not os.path.exists(repo_dir):
        return detected

    # Collect all file extensions and config files
    extensions_found = set()
    files_found = set()

    for root, dirs, files in os.walk(repo_dir):
        # Skip common non-source directories
        dirs[:] = [d for d in dirs if d not in {
            'node_modules', '.git', '__pycache__', 'venv', '.venv',
            'env', 'build', 'dist', 'target', 'bin', 'obj', '.idea',
            '.vscode', 'vendor', '.tox', '.mypy_cache', '.pytest_cache'
        }]
        for f in files:
            _, ext = os.path.splitext(f)
            if ext:
                extensions_found.add(ext.lower())
            files_found.add(f)

    for lang, sigs in LANGUAGE_SIGNATURES.items():
        # Check extensions
        if any(ext in extensions_found for ext in sigs["extensions"]):
            detected.append(lang)
            continue
        # Check config files
        for cfg in sigs["config_files"]:
            if "*" in cfg:
                # Glob pattern — check extension
                ext = cfg.replace("*", "")
                if any(f.endswith(ext) for f in files_found):
                    detected.append(lang)
                    break
            elif cfg in files_found:
                detected.append(lang)
                break

    return detected


def detect_test_framework(repo_dir: str, language: str) -> Optional[str]:
    """Detect which test framework is used for a given language."""
    lang_config = TEST_FRAMEWORK_DETECTION.get(language)
    if not lang_config:
        return None

    # Read relevant config files for framework markers
    file_contents = ""
    for cfg_file in lang_config.get("detect_in_files", []):
        cfg_path = os.path.join(repo_dir, cfg_file)
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_contents += f.read(50000)  # Cap at 50K per file
            except Exception:
                pass

    # Also scan test directories for framework-specific patterns
    for test_dir in lang_config.get("detect_in_dirs", []):
        test_path = os.path.join(repo_dir, test_dir)
        if os.path.isdir(test_path):
            for root, _, files in os.walk(test_path):
                for f in files[:20]:  # Check first 20 test files
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                            file_contents += fh.read(10000)
                    except Exception:
                        pass

    # Check each framework's markers
    for fw_name, fw_config in lang_config["frameworks"].items():
        for marker in fw_config["markers"]:
            if marker in file_contents:
                return fw_name

    return lang_config.get("default_framework")


def build_project_profile(repo_dir: str) -> ProjectProfile:
    """Build a complete project profile with all detected information."""
    profile = ProjectProfile()
    profile.languages = detect_languages(repo_dir)

    for lang in profile.languages:
        lang_config = TEST_FRAMEWORK_DETECTION.get(lang)
        if not lang_config:
            continue

        # Detect test framework
        fw = detect_test_framework(repo_dir, lang)
        if fw and fw in lang_config["frameworks"]:
            fw_config = lang_config["frameworks"][fw]
            profile.test_frameworks[lang] = [fw]
            profile.test_commands[lang] = fw_config["test_cmd"]
            profile.coverage_commands[lang] = fw_config["coverage_cmd"]
            profile.coverage_tools[lang] = [fw_config["coverage_tool"]]
            if fw_config["install"]:
                profile.install_commands[lang] = fw_config["install"]

        # Collect linters
        profile.linters[lang] = []
        profile.lint_commands[lang] = ""
        lint_cmds = []
        for linter_name, linter_config in lang_config.get("linters", {}).items():
            profile.linters[lang].append(linter_name)
            lint_cmds.append(linter_config["cmd"])
        if lint_cmds:
            profile.lint_commands[lang] = " && ".join(lint_cmds)

    # Detect build systems
    build_indicators = {
        "CMakeLists.txt": "cmake",
        "Makefile": "make",
        "meson.build": "meson",
        "pom.xml": "maven",
        "build.gradle": "gradle",
        "build.gradle.kts": "gradle",
        "Cargo.toml": "cargo",
        "go.mod": "go",
        "package.json": "npm",
        "Gemfile": "bundler",
        "composer.json": "composer",
    }
    for fname, build_sys in build_indicators.items():
        if os.path.exists(os.path.join(repo_dir, fname)):
            if build_sys not in profile.build_systems:
                profile.build_systems.append(build_sys)

    return profile
