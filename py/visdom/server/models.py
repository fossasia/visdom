import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Workspace(Base):
    __tablename__ = 'workspaces'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship("Membership", back_populates="workspace", cascade="all, delete-orphan")
    guest_links = relationship("GuestLink", back_populates="workspace", cascade="all, delete-orphan")

class Membership(Base):
    __tablename__ = 'memberships'

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey('workspaces.id'), nullable=False)
    user_id = Column(String(36), nullable=False)  # Assuming string user IDs for now
    role = Column(String(50), nullable=False, default="member")  # e.g., admin, member

    workspace = relationship("Workspace", back_populates="memberships")

class GuestLink(Base):
    __tablename__ = 'guest_links'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey('workspaces.id'), nullable=False)
    url_token = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    workspace = relationship("Workspace", back_populates="guest_links")
