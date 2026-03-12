# a2a/client.py
"""A2A client for inter-agent communication."""

import json
import logging
import httpx
from typing import Optional, Dict, Any, AsyncGenerator

from .models import Task, TaskSendRequest, Artifact, Message

logger = logging.getLogger(__name__)


class A2AClient:
    """Client for calling other A2A agents."""

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=300)

    async def get_agent_card(self, agent_name: str) -> dict:
        resp = await self._client.get(
            f"{self.base_url}/agents/{agent_name}/.well-known/agent.json"
        )
        resp.raise_for_status()
        return resp.json()

    async def send_task(
        self,
        agent_name: str,
        message_text: str,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """Send a task to an agent and wait for completion."""
        parts = [{"type": "text", "text": message_text}]
        if data:
            parts.append({"type": "data", "data": data})

        request = TaskSendRequest(
            params={
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "parts": parts,
                },
            }
        )

        resp = await self._client.post(
            f"{self.base_url}/agents/{agent_name}/tasks/send",
            json=request.model_dump(),
        )
        resp.raise_for_status()
        return Task(**resp.json())

    async def send_task_streaming(
        self,
        agent_name: str,
        message_text: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Task, None]:
        """Send a task and stream updates."""
        parts = [{"type": "text", "text": message_text}]
        if data:
            parts.append({"type": "data", "data": data})

        request = TaskSendRequest(
            params={
                "message": {"role": "user", "parts": parts},
            }
        )

        async with self._client.stream(
            "POST",
            f"{self.base_url}/agents/{agent_name}/tasks/sendSubscribe",
            json=request.model_dump(),
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    task_data = json.loads(line[6:])
                    yield Task(**task_data)

    async def close(self):
        await self._client.aclose()