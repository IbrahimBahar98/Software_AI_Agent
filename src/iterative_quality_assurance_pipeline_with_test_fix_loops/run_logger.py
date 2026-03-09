import json
import os
import datetime
from typing import Any, Dict

class RunLogger:
    """Handles structured logging for CrewAI executions to support observability."""
    
    def __init__(self, workspace_dir: str = "./workspace"):
        self.workspace_dir = workspace_dir
        self.run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.workspace_dir, f".run_log_{self.run_id}.json")
        self.log_data = {
            "run_id": self.run_id,
            "start_time": datetime.datetime.now().isoformat(),
            "end_time": None,
            "tasks": [],
            "metrics": {
                "total_tokens": 0,
                "total_tool_calls": 0
            }
        }
        
    def step_callback(self, agent_output: Any):
        """Called after each step an agent takes."""
        # agent_output can be AgentAction or AgentFinish
        try:
            if hasattr(agent_output, 'tool'):
                self.log_data["metrics"]["total_tool_calls"] += 1
                
            # Log incrementally to prevent data loss on crash
            self._save()
        except Exception:
            pass

    def task_callback(self, task_output: Any):
        """Called after a task completes."""
        try:
            task_entry = {
                "description": getattr(task_output, 'description', 'Unknown Task'),
                "agent": getattr(task_output, 'agent', 'Unknown Agent'),
                "output": str(getattr(task_output, 'raw', ''))
            }
            self.log_data["tasks"].append(task_entry)
            
            # Simple token estimation since CrewAI tokens are sometimes buried
            # Rough estimate: 1 word ~ 1.3 tokens
            words = len(str(task_entry["output"]).split())
            self.log_data["metrics"]["total_tokens"] += int(words * 1.3)
            
            self._save()
        except Exception:
            pass
            
    def finish_run(self):
        """Finalize the log."""
        self.log_data["end_time"] = datetime.datetime.now().isoformat()
        self._save()
        self._print_summary()
        
    def _save(self):
        """Write current state to file."""
        os.makedirs(self.workspace_dir, exist_ok=True)
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self.log_data, f, indent=2)
        except Exception:
            pass
            
    def _print_summary(self):
        """Print a nice summary to console."""
        print("\n" + "="*50)
        print("📊 PIPELINE RUN SUMMARY")
        print("="*50)
        print(f"Log File:   {self.log_file}")
        print(f"Tasks:      {len(self.log_data['tasks'])}")
        print(f"Tools Used: {self.log_data['metrics']['total_tool_calls']}")
        print(f"Est Tokens: ~{self.log_data['metrics']['total_tokens']}")
        print("="*50 + "\n")
