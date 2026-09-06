"""Durable MCP connection identities and operation receipts, per profile DB."""

from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from database import Base
from core.profile_context import get_current_profile


class McpClient(Base):
    __tablename__ = "mcp_clients"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    profile_id = Column(String, nullable=False, default=get_current_profile)
    credential_hash = Column(String, nullable=False, unique=True)
    installation = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class McpOperation(Base):
    __tablename__ = "mcp_operations"
    id = Column(String, primary_key=True)
    client_id = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    request_key = Column(String, nullable=False)
    input_hash = Column(String, nullable=False)
    state = Column(String, nullable=False, default="queued")
    input_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    chat_id = Column(Integer, nullable=True)
    controller_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("operation", "request_key", name="uq_mcp_request"),
    )
