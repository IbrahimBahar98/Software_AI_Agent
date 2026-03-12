"""
Checkpoint tool for the QA pipeline.
Saves and loads pipeline progress state for recovery and reporting.
"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import json
import os
import datetime
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import CHECKPOINT_DIR

# Max history entries to prevent unbounded growth
MAX_HISTORY_ENTRIES = 50


class CheckpointInput(BaseModel):
    """Input schema for Checkpoint Tool."""
    operation: str = Field(
        default="save",
        description=(
            "Operation to perform:\n"
            "  'save'    — Save state for a phase (requires phase name)\n"
            "  'load'    — Read the full current state\n"
            "  'summary' — Get a concise summary of all completed phases\n"
            "  'clear'   — Reset checkpoint state for a fresh run"
        )
    )
    phase: str = Field(
        default="",
        description="Phase name for save operation (e.g., 'repo_analysis', 'tests_passed', 'lint_complete')."
    )
    branch: str = Field(
        default="",
        description="Current working branch name."
    )
    data: str = Field(
        default="{}",
        description="JSON string of arbitrary state data to save."
    )


class CheckpointTool(BaseTool):
    """Tool for saving and loading pipeline progress state."""

    name: str = "checkpoint_tool"
    description: str = (
        "Saves or loads the pipeline's progress state.\n"
        "Operations:\n"
        "  - 'save': Save state with phase name and data. Enables recovery if interrupted.\n"
        "  - 'load': Read the full current state including all history.\n"
        "  - 'summary': Get a concise summary of all completed phases (useful for QA report).\n"
        "  - 'clear': Reset all checkpoint state for a fresh run.\n"
        "Example: operation='save', phase='lint_complete', data='{\"passed\": true}'"
    )
    args_schema: Type[BaseModel] = CheckpointInput
    checkpoint_dir: str = CHECKPOINT_DIR

    def __init__(self, checkpoint_dir: str = None, **kwargs):
        super().__init__(**kwargs)
        if checkpoint_dir:
            self.checkpoint_dir = os.path.abspath(checkpoint_dir)
        else:
            self.checkpoint_dir = CHECKPOINT_DIR
        self._checkpoint_file = os.path.join(self.checkpoint_dir, "pipeline_state.json")

    def _load_state(self) -> dict:
        """Load state from file, returning empty state if not found."""
        if not os.path.exists(self._checkpoint_file):
            return {"history": [], "phases_completed": []}
        try:
            with open(self._checkpoint_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            # Ensure required keys
            if "history" not in state:
                state["history"] = []
            if "phases_completed" not in state:
                state["phases_completed"] = []
            return state
        except (json.JSONDecodeError, Exception):
            return {"history": [], "phases_completed": []}

    def _save_state(self, state: dict) -> None:
        """Write state to file."""
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        with open(self._checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)

    def _run(
        self,
        operation: str = "save",
        phase: str = "",
        branch: str = "",
        data: str = "{}",
    ) -> str:
        """Dispatch to the appropriate operation."""
        try:
            op = operation.strip().lower()
            if op == "load":
                return self._op_load()
            elif op == "summary":
                return self._op_summary()
            elif op == "clear":
                return self._op_clear()
            elif op == "save":
                return self._op_save(phase, branch, data)
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unknown operation '{operation}'. Use: save, load, summary, clear"
                })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Checkpoint operation failed: {type(e).__name__}: {e}"
            })

    def _op_load(self) -> str:
        """Load the full current checkpoint state."""
        state = self._load_state()
        if not state.get("history"):
            return json.dumps({
                "success": True,
                "state": None,
                "message": "No checkpoint found. This is a fresh run."
            })
        return json.dumps({"success": True, "state": state})

    def _op_summary(self) -> str:
        """Get a concise summary of all completed phases."""
        state = self._load_state()
        history = state.get("history", [])

        if not history:
            return json.dumps({
                "success": True,
                "summary": "No phases completed yet.",
                "phases": []
            })

        phases = []
        for entry in history:
            phase_info = {
                "phase": entry.get("phase", "unknown"),
                "timestamp": entry.get("timestamp", ""),
            }
            # Include key metrics from data if available
            entry_data = entry.get("data", {})
            if isinstance(entry_data, dict):
                # Extract key fields that are useful for reporting
                for key in ["passed", "failed", "skipped", "coverage", "errors",
                            "tests_passed", "languages", "status", "message"]:
                    if key in entry_data:
                        phase_info[key] = entry_data[key]
            phases.append(phase_info)

        return json.dumps({
            "success": True,
            "total_phases": len(phases),
            "current_phase": state.get("current_phase", "unknown"),
            "branch": state.get("branch", ""),
            "phases": phases,
        }, indent=2)

    def _op_clear(self) -> str:
        """Reset checkpoint state."""
        try:
            if os.path.exists(self._checkpoint_file):
                os.remove(self._checkpoint_file)
            return json.dumps({
                "success": True,
                "message": "Checkpoint cleared. Ready for fresh run."
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to clear checkpoint: {e}"
            })

    def _op_save(self, phase: str, branch: str, data: str) -> str:
        """Save pipeline checkpoint state."""
        if not phase:
            return json.dumps({
                "success": False,
                "error": "Phase name is required for save operation."
            })

        state = self._load_state()

        # Parse data
        try:
            parsed_data = json.loads(data)
        except json.JSONDecodeError:
            parsed_data = {"raw": data}

        new_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "phase": phase,
            "branch": branch,
            "data": parsed_data,
        }

        state["current_phase"] = phase
        if branch:
            state["branch"] = branch

        state["history"].append(new_entry)

        # Track completed phases
        if phase not in state.get("phases_completed", []):
            state.setdefault("phases_completed", []).append(phase)

        # Trim history to prevent unbounded growth
        if len(state["history"]) > MAX_HISTORY_ENTRIES:
            state["history"] = state["history"][-MAX_HISTORY_ENTRIES:]

        self._save_state(state)

        return json.dumps({
            "success": True,
            "message": f"Checkpoint '{phase}' saved.",
            "total_phases": len(state.get("phases_completed", [])),
            "checkpoint_file": self._checkpoint_file,
        })