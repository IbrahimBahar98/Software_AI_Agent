# a2a/models.py
"""A2A protocol data models (Google A2A spec compliant)."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from datetime import datetime
import uuid


# ── Agent Card (self-description) ────────────────────────

class AgentSkill(BaseModel):
    """A specific capability of an agent."""
    id: str
    name: str
    description: str
    tags: List[str] = []
    examples: List[str] = []


class AgentCapabilities(BaseModel):
    """What protocols the agent supports."""
    streaming: bool = True
    pushNotifications: bool = False
    stateTransitionHistory: bool = True


class AgentCard(BaseModel):
    """A2A Agent Card — describes an agent's identity and capabilities."""
    name: str
    description: str
    url: str  # Base URL for this agent
    version: str = "1.0.0"
    capabilities: AgentCapabilities = AgentCapabilities()
    skills: List[AgentSkill] = []
    defaultInputModes: List[str] = ["application/json", "text/plain"]
    defaultOutputModes: List[str] = ["application/json", "text/plain"]


# ── Task Models ──────────────────────────────────────────

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class Artifact(BaseModel):
    """Structured data passed between agents."""
    name: str
    description: Optional[str] = None
    parts: List[Dict[str, Any]]  # [{"type": "text", "text": "..."}, {"type": "data", "data": {...}}]
    index: int = 0
    append: bool = False
    lastChunk: bool = True


class Message(BaseModel):
    """A message in a task conversation."""
    role: Literal["user", "agent"]
    parts: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None


class TaskStatus(BaseModel):
    """Current status of a task."""
    state: TaskState
    message: Optional[Message] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class Task(BaseModel):
    """A2A Task — the unit of work between agents."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: Optional[str] = None
    status: TaskStatus
    artifacts: List[Artifact] = []
    history: List[Message] = []
    metadata: Optional[Dict[str, Any]] = None


class TaskSendRequest(BaseModel):
    """Request to send a task to an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    params: Dict[str, Any]  # Contains message, sessionId, etc.


class TaskSendResponse(BaseModel):
    """Response from an agent after processing a task."""
    id: str
    result: Optional[Task] = None
    error: Optional[Dict[str, Any]] = None