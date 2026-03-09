from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import json
import os
import datetime

class CheckpointInput(BaseModel):
    """Input schema for Checkpoint Tool."""
    phase: str = Field(..., description="The current phase or milestone name (e.g., 'tests_passed', 'dev_branch_created').")
    branch: str = Field(default="", description="The current working branch name.")
    data: str = Field(default="{}", description="JSON string of any arbitrary state data to save.")

class CheckpointTool(BaseTool):
    """Tool for saving the pipeline's progress state persistently.
    
    This allows resuming operations across large pipelines if a crash happens
    or if run sequentially.
    """

    name: str = "checkpoint_tool"
    description: str = (
        "Saves the current state of the pipeline to a checkpoint file. "
        "Useful for persisting branch names or progress flags so the system "
        "can recover gracefully."
    )
    args_schema: Type[BaseModel] = CheckpointInput
    workspace_dir: str = "./workspace"
    checkpoint_file: str = ".pipeline_state.json"

    def __init__(self, workspace_dir: str = "./workspace", **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = workspace_dir
        self.checkpoint_file = os.path.join(workspace_dir, ".pipeline_state.json")

    def _run(self, phase: str, branch: str = "", data: str = "{}") -> str:
        """Save pipeline checkpoint state."""
        try:
            os.makedirs(self.workspace_dir, exist_ok=True)
            
            # Load existing state if any
            state = {"history": []}
            if os.path.exists(self.checkpoint_file):
                try:
                    with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except json.JSONDecodeError:
                    pass # Corrupt file, overwrite
            
            # Try to parse the arbitrary data
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
            
            # Update state
            state["current_phase"] = phase
            if branch:
                state["branch"] = branch
            state["history"].append(new_entry)
            
            with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
                
            return json.dumps({
                "success": True, 
                "message": f"Checkpoint '{phase}' saved successfully."
            })

        except Exception as e:
            return json.dumps({
                "success": False, 
                "error": f"Failed to save checkpoint: {str(e)}"
            })
