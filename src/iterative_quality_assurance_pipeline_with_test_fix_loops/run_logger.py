import json
import os
import sys
import datetime
from typing import Any
from iterative_quality_assurance_pipeline_with_test_fix_loops.config import LOG_DIR


class RunLogger:
    """Structured logging for CrewAI pipeline runs with rich step tracking."""

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(LOG_DIR, f"run_{self.run_id}.json")
        self.log_data = {
            "run_id": self.run_id,
            "start_time": datetime.datetime.now().isoformat(),
            "end_time": None,
            "tasks": [],
            "steps": [],
            "metrics": {
                "estimated_output_tokens": 0,
                "total_tool_calls": 0,
                "large_output_warnings": 0,
            }
        }
        self._save()

    def step_callback(self, agent_output: Any):
        """Called after each agent step — logs tool calls and flags anomalies."""
        try:
            step_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "tool_call" if hasattr(agent_output, 'tool') else "reasoning",
            }

            if hasattr(agent_output, 'tool'):
                self.log_data["metrics"]["total_tool_calls"] += 1
                step_entry["tool"] = str(getattr(agent_output, 'tool', ''))
                tool_input = str(getattr(agent_output, 'tool_input', ''))
                step_entry["tool_input_preview"] = tool_input[:500]
                step_entry["tool_input_length"] = len(tool_input)

            if hasattr(agent_output, 'return_values'):
                output_text = str(agent_output.return_values)
                step_entry["output_length"] = len(output_text)
                if len(output_text) > 30000:
                    step_entry["warning"] = "LARGE_OUTPUT"
                    self.log_data["metrics"]["large_output_warnings"] += 1

            if hasattr(agent_output, 'log'):
                log_text = str(agent_output.log)
                step_entry["log_preview"] = log_text[:300]

            self.log_data["steps"].append(step_entry)

            # Keep bounded — retain last 300 steps
            if len(self.log_data["steps"]) > 300:
                self.log_data["steps"] = self.log_data["steps"][-300:]

            self._save()
        except Exception as e:
            print(f"[RunLogger] step_callback warning: {e}", file=sys.stderr)

    def task_callback(self, task_output: Any):
        """Called after a task completes."""
        try:
            output_text = str(getattr(task_output, 'raw', ''))
            task_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "description": str(getattr(task_output, 'description', 'Unknown'))[:200],
                "agent": str(getattr(task_output, 'agent', 'Unknown')),
                "output_length": len(output_text),
                "output_preview": output_text[:500],
            }
            self.log_data["tasks"].append(task_entry)

            # Token estimation (~4 chars per token for English)
            self.log_data["metrics"]["estimated_output_tokens"] += len(output_text) // 4

            self._save()
        except Exception as e:
            print(f"[RunLogger] task_callback warning: {e}", file=sys.stderr)

    def finish_run(self):
        """Finalize the log."""
        self.log_data["end_time"] = datetime.datetime.now().isoformat()
        self._save()
        self._print_summary()

    def _save(self):
        """Write current state to file."""
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self.log_data, f, indent=2)
        except Exception as e:
            print(f"[RunLogger] save warning: {e}", file=sys.stderr)

    def _print_summary(self):
        """Print a summary to console."""
        print("\n" + "=" * 50)
        print("PIPELINE RUN SUMMARY")
        print("=" * 50)
        print(f"  Log File:       {self.log_file}")
        print(f"  Tasks:          {len(self.log_data['tasks'])}")
        print(f"  Tool Calls:     {self.log_data['metrics']['total_tool_calls']}")
        print(f"  Est. Tokens:    ~{self.log_data['metrics']['estimated_output_tokens']}")
        print(f"  Large Outputs:  {self.log_data['metrics']['large_output_warnings']}")

        if self.log_data.get("start_time") and self.log_data.get("end_time"):
            try:
                start = datetime.datetime.fromisoformat(self.log_data["start_time"])
                end = datetime.datetime.fromisoformat(self.log_data["end_time"])
                duration = end - start
                print(f"  Duration:       {duration}")
            except Exception:
                pass

        print("=" * 50 + "\n")