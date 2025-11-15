"""
Pydantic schemas for request/response validation
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


# =====================================================================
# Authentication Schemas
# =====================================================================

class UserRegisterRequest(BaseModel):
    """Schema for user registration request"""
    username: str = Field(..., min_length=3, max_length=100, description="Username 3-100 chars")
    password: str = Field(..., min_length=6, max_length=1000, description="Password 6-1000 chars")
    email: Optional[str] = Field(None, description="Optional email address")

    class Config:
        json_schema_extra = {
            "example": {
                "username": "john_doe",
                "password": "securepass123",
                "email": "john@example.com"
            }
        }


class UserLoginRequest(BaseModel):
    """Schema for user login request"""
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=1000)

    class Config:
        json_schema_extra = {
            "example": {
                "username": "john_doe",
                "password": "securepass123"
            }
        }


class TokenResponse(BaseModel):
    """Schema for token response"""
    access_token: str
    token_type: str = "bearer"
    username: str
    user_id: str

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "username": "john_doe",
                "user_id": "123456-john_doe"
            }
        }


class UserResponse(BaseModel):
    """Schema for user info response"""
    username: str
    user_id: str
    email: Optional[str] = None
    created_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "username": "john_doe",
                "user_id": "123456-john_doe",
                "email": "john@example.com",
                "created_at": "2025-11-15T10:30:00"
            }
        }


class ErrorResponse(BaseModel):
    """Schema for error responses"""
    error: str
    status_code: int

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Username already exists",
                "status_code": 400
            }
        }


# =====================================================================
# Chat & Moderation Schemas
# =====================================================================

class BlockRequest(BaseModel):
    """Schema for block/unblock requests"""
    username: str = Field(..., min_length=1, max_length=100)


class ReportRequest(BaseModel):
    """Schema for reporting users"""
    username: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=500)
    message_id: Optional[str] = None


class ChatMessage(BaseModel):
    """Schema for chat messages"""
    sender: str
    sender_id: Optional[str]
    original: str
    translations: dict
    timestamp: datetime
    message_id: str
    color: str


class ActiveUser(BaseModel):
    """Schema for active users list"""
    username: str
    color: str
