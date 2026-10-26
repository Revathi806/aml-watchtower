from pydantic import BaseModel, Field
from typing import Optional

class LoginRequest(BaseModel):
    email: str
    password: str

class AlertUpdate(BaseModel):
    status: str = Field(pattern="^(Open|Assigned|Resolved|Escalated)$")
    assigned_to: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)

class RuleUpdate(BaseModel):
    enabled: bool
    threshold: dict
    weight: int = Field(ge=0, le=100)


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(pattern="^(analyst|admin)$")
