from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import json
import os
import datetime
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import CHECKPOINT_DIR


class CheckpointInput(BaseModel):
    """Input schema for Checkpoint Tool."""
    operation: str = Field(
        default="save",
        description="Operation: 'save' to save state, 'load' to read current state."
    )
    phase: str = Field(default="", description="Phase name (required for save, e.g., 'tests_passed').")
    branch: str = Field(default="", description="Current working branch name.")
    data: str = Field(default="{}", description="JSON string of arbitrary state data to save.")


class CheckpointTool(BaseTool):
    """Tool for saving and loading pipeline progress state."""

    name: str = "checkpoint_tool"
    description: str = (
        "Saves or loads the pipeline's progress state. Use operation='save' with "
        "phase name to persist progress. Use operation='load' to read current state. "
        "This enables recovery if the pipeline is interrupted."
    )
    args_schema: Type[BaseModel] = CheckpointInput
    checkpoint_dir: str = CHECKPOINT_DIR

    def __init__(self, **kwargs):
        kwargs.pop("workspace_dir", None)
        kwargs.pop("checkpoint_dir", None)
        super().__init__(**kwargs)
        self.checkpoint_dir = CHECKPOINT_DIR
        self._checkpoint_file = os.path.join(CHECKPOINT_DIR, "pipeline_state.json")

    def _run(self, operation: str = "save", phase: str = "", branch: str = "", data: str = "{}") -> str:
        """Save or load checkpoint state."""
        if operation == "load":
            return self._load()
        return self._save(phase, branch, data)

    def _load(self) -> str:
        """Load the current checkpoint state."""
        try:
            if not os.path.exists(self._checkpoint_file):
                return json.dumps({
                    "success": True,
                    "state": None,
                    "message": "No checkpoint found. This is a fresh run."
                })
            with open(self._checkpoint_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            return json.dumps({"success": True, "state": state})
        except Exception as e:
            return json.dumps({"success": False, "error": f"Failed to load checkpoint: {str(e)}"})

    def _save(self, phase: str, branch: str, data: str) -> str:
        """Save pipeline checkpoint state."""
        try:
            os.makedirs(self.checkpoint_dir, exist_ok=True)

            # Load existing state
            state = {"history": []}
            if os.path.exists(self._checkpoint_file):
                try:
                    with open(self._checkpoint_file, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except (json.JSONDecodeError, Exception):
                    state = {"history": []}

            # Parse arbitrary data
            try:
                parsed_data = json.loads(data)
            except json.JSONDecodeError:
                parsed_data = {"raw": data}

            new_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "phase": phase,
                "branch": branch,
                "data": parsed_data
            }

            state["current_phase"] = phase
            if branch:
                state["branch"] = branch
            if "history" not in state:
                state["history"] = []
            state["history"].append(new_entry)

            with open(self._checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)

            return json.dumps({
                "success": True,
                "message": f"Checkpoint '{phase}' saved successfully.",
                "checkpoint_file": self._checkpoint_file
            })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to save checkpoint: {str(e)}"
            })
