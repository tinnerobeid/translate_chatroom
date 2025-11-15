"""
Moderation routes (block, unblock, report users)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import logging

from app.schemas import BlockRequest, ReportRequest
from app.models import UserRepository, BlockRepository, ReportRepository
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["moderation"])


@router.post(
    "/block",
    summary="Block a user",
    description="Add a user to your block list"
)
async def block_user(
    request: BlockRequest,
    current_user: dict = Depends(get_current_user)
):
    """Block a user from messaging you"""
    try:
        # Check if target user exists
        if not UserRepository.user_exists(request.username):
            return JSONResponse(
                {"error": "User not found"},
                status_code=404
            )
        
        # Prevent blocking yourself
        if request.username == current_user["username"]:
            return JSONResponse(
                {"error": "Cannot block yourself"},
                status_code=400
            )
        
        BlockRepository.block_user(current_user["user_id"], request.username)
        logger.info(f"User {current_user['username']} blocked {request.username}")
        
        return {"message": f"User '{request.username}' has been blocked"}
    
    except Exception as e:
        logger.error(f"Block user error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )


@router.post(
    "/unblock",
    summary="Unblock a user",
    description="Remove a user from your block list"
)
async def unblock_user(
    request: BlockRequest,
    current_user: dict = Depends(get_current_user)
):
    """Unblock a previously blocked user"""
    try:
        BlockRepository.unblock_user(current_user["user_id"], request.username)
        logger.info(f"User {current_user['username']} unblocked {request.username}")
        
        return {"message": f"User '{request.username}' has been unblocked"}
    
    except Exception as e:
        logger.error(f"Unblock user error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )


@router.get(
    "/blocked",
    summary="Get blocked users",
    description="Get list of users you have blocked"
)
async def get_blocked_users(current_user: dict = Depends(get_current_user)):
    """Get list of blocked users"""
    try:
        blocked = BlockRepository.get_blocked_users(current_user["user_id"])
        return {"blocked_users": list(blocked)}
    
    except Exception as e:
        logger.error(f"Get blocked users error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )


@router.post(
    "/report",
    summary="Report a user",
    description="Submit a report for inappropriate user behavior"
)
async def report_user(
    request: ReportRequest,
    current_user: dict = Depends(get_current_user)
):
    """Report a user for violating community guidelines"""
    try:
        # Check if target user exists
        if not UserRepository.user_exists(request.username):
            return JSONResponse(
                {"error": "User not found"},
                status_code=404
            )
        
        # Prevent reporting yourself
        if request.username == current_user["username"]:
            return JSONResponse(
                {"error": "Cannot report yourself"},
                status_code=400
            )
        
        report = ReportRepository.add_report(
            reporter_id=current_user["user_id"],
            reported_username=request.username,
            reason=request.reason,
            message_id=request.message_id
        )
        
        logger.info(f"Report submitted: {report['id']}")
        
        return {
            "message": "Report submitted successfully",
            "report_id": report["id"]
        }
    
    except Exception as e:
        logger.error(f"Report user error: {e}")
        return JSONResponse(
            {"error": "Internal server error"},
            status_code=500
        )
