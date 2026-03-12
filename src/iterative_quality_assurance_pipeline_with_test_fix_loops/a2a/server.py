# a2a/server.py
"""A2A-compliant server that hosts pipeline agents."""

import asyncio
import json
import logging
from typing import Dict, Optional, AsyncGenerator
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager

from .models import (
    AgentCard, AgentSkill, AgentCapabilities,
    Task, TaskState, TaskStatus, TaskSendRequest,
    Message, Artifact,
)

logger = logging.getLogger(__name__)


class A2AAgentServer:
    """
    Hosts a single logical agent with A2A protocol endpoints.
    Multiple instances can run on different ports, or a router
    can multiplex them on one port.
    """

    def __init__(self, agent_card: AgentCard, handler):
        """
        Args:
            agent_card: The agent's self-description
            handler: Async callable(task: Task) -> AsyncGenerator[Task]
                     Yields task updates as processing progresses.
        """
        self.agent_card = agent_card
        self.handler = handler
        self.tasks: Dict[str, Task] = {}

    def get_agent_card(self) -> dict:
        return self.agent_card.model_dump()

    async def handle_task_send(self, request: TaskSendRequest) -> Task:
        """Process a task synchronously (non-streaming)."""
        task = self._create_task(request)
        self.tasks[task.id] = task

        # Run handler to completion
        async for updated_task in self.handler(task):
            self.tasks[task.id] = updated_task

        return self.tasks[task.id]

    async def handle_task_send_subscribe(
        self, request: TaskSendRequest
    ) -> AsyncGenerator[str, None]:
        """Process a task with SSE streaming updates."""
        task = self._create_task(request)
        self.tasks[task.id] = task

        async for updated_task in self.handler(task):
            self.tasks[task.id] = updated_task
            yield f"data: {json.dumps(updated_task.model_dump())}\n\n"

    async def handle_get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def _create_task(self, request: TaskSendRequest) -> Task:
        params = request.params
        message = Message(
            role="user",
            parts=params.get("message", {}).get("parts", []),
            metadata=params.get("message", {}).get("metadata"),
        )
        return Task(
            id=request.id,
            sessionId=params.get("sessionId"),
            status=TaskStatus(state=TaskState.SUBMITTED),
            history=[message],
        )


def create_a2a_app(agents: Dict[str, A2AAgentServer]) -> FastAPI:
    """Create a FastAPI app hosting multiple A2A agents."""

    app = FastAPI(title="QA Pipeline A2A Server")

    @app.get("/.well-known/agent.json")
    async def agent_card_default():
        """Return the primary agent card (or a directory of agents)."""
        return {
            "agents": {
                name: agent.get_agent_card()
                for name, agent in agents.items()
            }
        }

    @app.get("/agents/{agent_name}/.well-known/agent.json")
    async def agent_card(agent_name: str):
        if agent_name not in agents:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        return agents[agent_name].get_agent_card()

    @app.post("/agents/{agent_name}/tasks/send")
    async def task_send(agent_name: str, request: Request):
        if agent_name not in agents:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        body = await request.json()
        req = TaskSendRequest(**body)
        result = await agents[agent_name].handle_task_send(req)
        return result.model_dump()

    @app.post("/agents/{agent_name}/tasks/sendSubscribe")
    async def task_send_subscribe(agent_name: str, request: Request):
        if agent_name not in agents:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        body = await request.json()
        req = TaskSendRequest(**body)
        return StreamingResponse(
            agents[agent_name].handle_task_send_subscribe(req),
            media_type="text/event-stream",
        )

    @app.get("/agents/{agent_name}/tasks/{task_id}")
    async def get_task(agent_name: str, task_id: str):
        task = await agents[agent_name].handle_get_task(task_id)
        if not task:
            raise HTTPException(404, f"Task '{task_id}' not found")
        return task.model_dump()

    return app