"""
Authentication routes (register, login, token verification)
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
import jwt
from datetime import datetime, timedelta
from typing import Optional
import os
import logging

from app.schemas import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse, ErrorResponse
from app.models import UserRepository, verify_password, BlockRepository, ReportRepository

logger = logging.getLogger(__name__)

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise ValueError("SECRET_KEY environment variable is required in production")
    SECRET_KEY = "dev-secret-key-change-for-production"
    logger.warning("⚠️  Using default SECRET_KEY. Set SECRET_KEY environment variable for production.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

router = APIRouter(prefix="/api", tags=["auth"])


# =====================================================================
# Token Management
# =====================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# =====================================================================
# Dependency: Get Current User
# =====================================================================

def get_current_user(authorization: str = Header(None)) -> dict:
    """
    Extract and verify user from Bearer token in Authorization header
    
    Returns:
        dict: {"username": str, "user_id": str}
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    username = payload.get("sub")
    user_id = payload.get("user_id")
    
    if not username or not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    user = UserRepository.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return {"username": username, "user_id": user_id}


# =====================================================================
# Routes
# =====================================================================

@router.post(
    "/register",
    response_model=TokenResponse,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Register a new user",
    description="Create a new user account with username and password"
)
async def register(request: UserRegisterRequest):
    """
    Register a new user.
    
    - **username**: 3-100 characters
    - **password**: 6-1000 characters  
    - **email**: optional email address
    """
    try:
        # Validate username
        if len(request.username.strip()) < 3:
            return JSONResponse(
                {"error": "Username must be at least 3 characters"},
                status_code=400
            )
        
        # Check if user already exists
        if UserRepository.user_exists(request.username):
            return JSONResponse(
                {"error": "Username already exists"},
                status_code=409
            )
        
        # Create user
        user = UserRepository.create_user(
            username=request.username,
            password=request.password,
            email=request.email
        )
        
        # Create token
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}
        )
        
        logger.info(f"User registered: {user.username}")
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            username=user.username,
            user_id=user.id
        )
    
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Login user",
    description="Authenticate with username and password"
)
async def login(request: UserLoginRequest):
    """
    Login with username and password.
    
    Returns access token if credentials are valid.
    """
    try:
        user = UserRepository.get_user_by_username(request.username)
        
        if not user or not verify_password(request.password, user.password_hash):
            return JSONResponse(
                {"error": "Invalid username or password"},
                status_code=401
            )
        
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}
        )
        
        logger.info(f"User logged in: {user.username}")
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            username=user.username,
            user_id=user.id
        )
    
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Get current user info",
    description="Retrieve authenticated user's information"
)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's information"""
    try:
        user = UserRepository.get_user_by_username(current_user["username"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return UserResponse(
            username=user.username,
            user_id=user.id,
            email=user.email,
            created_at=user.created_at
        )
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/logout",
    summary="Logout user",
    description="Invalidate the current session (client-side implementation)"
)
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout user (token-based, so just return success).
    Client should discard the token.
    """
    logger.info(f"User logged out: {current_user['username']}")
    return {"message": "Logged out successfully"}
