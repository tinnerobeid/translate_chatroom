"""
Database models and user management utilities
"""
import json
import os
import random
import logging
from typing import Optional, Dict, Set
import bcrypt
from datetime import datetime

logger = logging.getLogger(__name__)

# File-based storage paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")
BLOCKS_FILE = os.path.join(DATA_DIR, "blocks.json")
REPORTS_FILE = os.path.join(DATA_DIR, "reports.json")


# =====================================================================
# User Model
# =====================================================================

class User:
    """User model"""
    def __init__(
        self,
        id: str,
        username: str,
        password_hash: str,
        email: Optional[str] = None,
        created_at: str = None
    ):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "email": self.email,
            "created_at": self.created_at
        }

    @staticmethod
    def from_dict(data: dict):
        """Create User from dictionary"""
        return User(
            id=data["id"],
            username=data["username"],
            password_hash=data["password_hash"],
            email=data.get("email"),
            created_at=data.get("created_at")
        )


# =====================================================================
# JSON File Storage Utilities
# =====================================================================

def load_json_file(filename: str, default: dict = None) -> dict:
    """Load JSON file, return default if not exists"""
    if default is None:
        default = {}
    
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
    return default.copy()


def save_json_file(filename: str, data: dict):
    """Save data to JSON file"""
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")


# =====================================================================
# Password Management
# =====================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt with 12 rounds"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


# =====================================================================
# User Repository (CRUD operations)
# =====================================================================

class UserRepository:
    """Manages user data in JSON file"""
    
    @staticmethod
    def get_all_users() -> Dict[str, User]:
        """Get all users"""
        users_data = load_json_file(USERS_FILE, {})
        return {
            username: User.from_dict(user_data)
            for username, user_data in users_data.items()
        }
    
    @staticmethod
    def get_user_by_username(username: str) -> Optional[User]:
        """Get user by username"""
        users_data = load_json_file(USERS_FILE, {})
        if username in users_data:
            return User.from_dict(users_data[username])
        return None
    
    @staticmethod
    def get_user_by_id(user_id: str) -> Optional[User]:
        """Get user by ID"""
        users_data = load_json_file(USERS_FILE, {})
        for user_data in users_data.values():
            if user_data.get("id") == user_id:
                return User.from_dict(user_data)
        return None
    
    @staticmethod
    def create_user(username: str, password: str, email: Optional[str] = None) -> User:
        """Create and save new user"""
        users_data = load_json_file(USERS_FILE, {})
        
        if username in users_data:
            raise ValueError(f"Username '{username}' already exists")
        
        user_id = f"{random.randint(100000, 999999)}-{username}"
        user = User(
            id=user_id,
            username=username,
            password_hash=hash_password(password),
            email=email,
            created_at=datetime.now().isoformat()
        )
        
        users_data[username] = user.to_dict()
        save_json_file(USERS_FILE, users_data)
        return user
    
    @staticmethod
    def user_exists(username: str) -> bool:
        """Check if user exists"""
        users_data = load_json_file(USERS_FILE, {})
        return username in users_data


# =====================================================================
# Block Management
# =====================================================================

class BlockRepository:
    """Manages blocked users"""
    
    @staticmethod
    def get_blocked_users(user_id: str) -> Set[str]:
        """Get set of usernames blocked by user"""
        blocks_data = load_json_file(BLOCKS_FILE, {})
        return set(blocks_data.get(user_id, []))
    
    @staticmethod
    def is_blocked(user_id: str, blocked_username: str) -> bool:
        """Check if user has blocked another"""
        blocked = BlockRepository.get_blocked_users(user_id)
        return blocked_username in blocked
    
    @staticmethod
    def block_user(user_id: str, username_to_block: str):
        """Block a user"""
        blocks_data = load_json_file(BLOCKS_FILE, {})
        if user_id not in blocks_data:
            blocks_data[user_id] = []
        if username_to_block not in blocks_data[user_id]:
            blocks_data[user_id].append(username_to_block)
        save_json_file(BLOCKS_FILE, blocks_data)
    
    @staticmethod
    def unblock_user(user_id: str, username_to_unblock: str):
        """Unblock a user"""
        blocks_data = load_json_file(BLOCKS_FILE, {})
        if user_id in blocks_data and username_to_unblock in blocks_data[user_id]:
            blocks_data[user_id].remove(username_to_unblock)
            if not blocks_data[user_id]:
                del blocks_data[user_id]
        save_json_file(BLOCKS_FILE, blocks_data)


# =====================================================================
# Report Management
# =====================================================================

class ReportRepository:
    """Manages user reports"""
    
    @staticmethod
    def get_all_reports() -> list:
        """Get all reports"""
        data = load_json_file(REPORTS_FILE, {"reports": []})
        return data.get("reports", [])
    
    @staticmethod
    def add_report(reporter_id: str, reported_username: str, reason: str, message_id: Optional[str] = None):
        """Add a report"""
        data = load_json_file(REPORTS_FILE, {"reports": []})
        report = {
            "id": f"{datetime.now().isoformat()}-{random.randint(1000, 9999)}",
            "reporter_id": reporter_id,
            "reported_username": reported_username,
            "reason": reason,
            "message_id": message_id,
            "timestamp": datetime.now().isoformat()
        }
        data["reports"].append(report)
        save_json_file(REPORTS_FILE, data)
        logger.info(f"Report added: {report}")
        return report
