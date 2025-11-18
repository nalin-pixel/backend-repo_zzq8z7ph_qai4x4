"""
Database Schemas for Flex

Each Pydantic model represents a MongoDB collection (collection name is the lowercase class name).
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional

class Flexuser(BaseModel):
    """
    Users of the Flex app
    Collection: "flexuser"
    """
    email: EmailStr = Field(..., description="Unique email for login")
    display_name: str = Field(..., min_length=2, max_length=40)
    password_hash: str = Field(..., description="Hashed password (server-side only)")
    avatar: Optional[str] = Field(None, description="Avatar URL")
    high_score: int = Field(0, ge=0)
    is_active: bool = Field(True)

class Session(BaseModel):
    """
    Auth sessions mapped to tokens
    Collection: "session"
    """
    user_id: str
    token: str
    user_agent: Optional[str] = None
    expires_at: int = Field(..., description="Unix timestamp of expiry")

class Score(BaseModel):
    """
    Game scores for leaderboard
    Collection: "score"
    """
    user_id: str
    display_name: str
    value: int = Field(..., ge=0)
