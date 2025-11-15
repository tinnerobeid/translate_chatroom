from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from deep_translator import GoogleTranslator
from pydantic import BaseModel
import logging
import json
import random
import os
import hashlib
import jwt
import asyncio
import bcrypt
from datetime import datetime, timedelta
from typing import Optional

# Password hashing
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # Allow using default only in development mode
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise ValueError("SECRET_KEY environment variable is required in production")
    SECRET_KEY = "dev-secret-key-change-for-production"
    logger = logging.getLogger(__name__)
    logger.warning("⚠️  Using default SECRET_KEY. Set SECRET_KEY environment variable for production.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Input validation & limits
# ------------------------------------------------------------------
MAX_MESSAGE_LENGTH = 5000  # Max characters per message
MAX_USERNAME_LENGTH = 100
MAX_LANGUAGES = 20  # Max global languages allowed
MAX_PASSWORD_LENGTH = 1000

def validate_message(text: str) -> bool:
    """Validate message length and content"""
    if not text or len(text.strip()) == 0:
        return False
    if len(text) > MAX_MESSAGE_LENGTH:
        return False
    return True

# ------------------------------------------------------------------
# App + CORS
# ------------------------------------------------------------------
app = FastAPI(title="Translation Chat Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # open for dev/testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Static File Serving
# ------------------------------------------------------------------
# Get frontend path (works both locally and on Render)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Serve static files
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def read_root():
    """Serve the main frontend HTML"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend not found", "path": FRONTEND_DIR}

# ------------------------------------------------------------------
# deep-translator compatibility helpers
# ------------------------------------------------------------------
_supported_langs_cache: Optional[dict[str, str]] = None  # {name_lower: code}

def get_supported_languages_dict() -> dict[str, str]:
    """
    Returns {"english": "en", "french": "fr", ...} with lowercase names.
    Works across deep-translator versions where get_supported_languages
    may be a class method or instance method.
    """
    global _supported_langs_cache
    if _supported_langs_cache is not None:
        return _supported_langs_cache

    try:
        langs = GoogleTranslator.get_supported_languages(as_dict=True)  # newer versions
    except TypeError:
        langs = GoogleTranslator(source="auto", target="en").get_supported_languages(as_dict=True)  # older versions

    _supported_langs_cache = {name.lower(): code for name, code in langs.items()}
    return _supported_langs_cache

def normalize_lang(user_input: Optional[str]) -> Optional[str]:
    """
    Accepts a language code or a language name.
    Returns an ISO code if recognized, otherwise None.
    """
    if not user_input:
        return None
    text = user_input.strip().lower()
    if not text:
        return None

    try:
        name_to_code = get_supported_languages_dict()
        codes = set(name_to_code.values())
    except Exception:
        name_to_code = {}
        codes = {"en", "fr", "es", "de", "it", "pt", "ar", "hi", "ja", "ko", "ru", "sw"}

    if text in codes:
        return text
    if text in name_to_code:
        return name_to_code[text]
    return None

# ------------------------------------------------------------------
# Simple HTTP testing endpoints
# ------------------------------------------------------------------
@app.get("/languages")
async def languages():
    try:
        return {"supported_languages": get_supported_languages_dict()}
    except Exception as e:
        logger.error(f"/languages error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/translate")
async def translate_http(
    text: str = Query(..., description="Text to translate"),
    target: str = Query("fr", description="Target language code or name"),
    source: Optional[str] = Query(None, description="Optional source (code or name). Default: auto")
):
    try:
        name_to_code = get_supported_languages_dict()
        codes = set(name_to_code.values())

        tgt = target.lower()
        if tgt in name_to_code:
            tgt = name_to_code[tgt]
        if tgt not in codes:
            return JSONResponse({"error": f"Unknown target '{target}'"}, status_code=400)

        src = (source or "auto").lower()
        if src in name_to_code:
            src = name_to_code[src]

        translated = await asyncio.to_thread(GoogleTranslator(source=src, target=tgt).translate, text)
        return {"source": src, "target": tgt, "original": text, "translated": translated}
    except Exception as e:
        logger.error(f"/translate error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ------------------------------------------------------------------
# User Authentication & Data Storage
# ------------------------------------------------------------------
USERS_FILE = "users.json"
BLOCKS_FILE = "blocks.json"
REPORTS_FILE = "reports.json"

def load_json_file(filename: str, default: dict) -> dict:
    """Load JSON file, return default if not exists"""
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
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")

def get_password_hash(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password using bcrypt"""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT token"""
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

# User models
class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class BlockRequest(BaseModel):
    username: str

class ReportRequest(BaseModel):
    username: str
    reason: str
    message_id: Optional[str] = None

# ------------------------------------------------------------------
# WebSocket translation chat (per-user target language)
# ------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.global_languages: list[str] = []
        self.username_by_ws: dict[WebSocket, str] = {}
        self.user_id_by_ws: dict[WebSocket, str] = {}  # Store user ID from token
        self.username_colors: dict[WebSocket, str] = {}
        self.translator_cache: dict[str, GoogleTranslator] = {}
        self.blocked_users: dict[str, set] = {}  # user_id -> set of blocked usernames
        self.reports: list[dict] = []  # Store reports
        self._load_blocks()
        self._load_reports()

    def _load_blocks(self):
        """Load blocked users from file"""
        blocks_data = load_json_file(BLOCKS_FILE, {})
        for user_id, blocked_list in blocks_data.items():
            self.blocked_users[user_id] = set(blocked_list)

    def _save_blocks(self):
        """Save blocked users to file"""
        blocks_data = {
            user_id: list(blocked_usernames)
            for user_id, blocked_usernames in self.blocked_users.items()
        }
        save_json_file(BLOCKS_FILE, blocks_data)

    def _load_reports(self):
        """Load reports from file"""
        self.reports = load_json_file(REPORTS_FILE, {"reports": []}).get("reports", [])

    def _save_reports(self):
        """Save reports to file"""
        save_json_file(REPORTS_FILE, {"reports": self.reports})

    def is_blocked(self, user_id: str, blocked_username: str) -> bool:
        """Check if a user has blocked another user"""
        if user_id not in self.blocked_users:
            return False
        return blocked_username in self.blocked_users[user_id]

    def block_user(self, user_id: str, username_to_block: str):
        """Block a user"""
        if user_id not in self.blocked_users:
            self.blocked_users[user_id] = set()
        self.blocked_users[user_id].add(username_to_block)
        self._save_blocks()

    def unblock_user(self, user_id: str, username_to_unblock: str):
        """Unblock a user"""
        if user_id in self.blocked_users:
            self.blocked_users[user_id].discard(username_to_unblock)
            if not self.blocked_users[user_id]:
                del self.blocked_users[user_id]
            self._save_blocks()

    def add_report(self, reporter_id: str, reported_username: str, reason: str, message_id: Optional[str] = None):
        """Add a report"""
        report = {
            "id": datetime.now().isoformat() + "-" + str(random.randint(1000, 9999)),
            "reporter_id": reporter_id,
            "reported_username": reported_username,
            "reason": reason,
            "message_id": message_id,
            "timestamp": datetime.now().isoformat()
        }
        self.reports.append(report)
        self._save_reports()
        logger.info(f"Report added: {report}")

    def get_user_id(self, websocket: WebSocket) -> Optional[str]:
        """Get user ID from websocket"""
        return self.user_id_by_ws.get(websocket)

    def _generate_pastel_color(self) -> str:
        """Generate a random pastel color in hex format"""
        hue = random.randint(0, 360)
        saturation = random.randint(25, 45)  # Low saturation for pastel
        lightness = random.randint(75, 90)   # High lightness for pastel

        # Convert HSL to RGB
        c = (1 - abs(2 * lightness / 100 - 1)) * saturation / 100
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = lightness / 100 - c / 2

        if hue < 60:
            r, g, b = c, x, 0
        elif hue < 120:
            r, g, b = x, c, 0
        elif hue < 180:
            r, g, b = 0, c, x
        elif hue < 240:
            r, g, b = 0, x, c
        elif hue < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
        return f"#{r:02x}{g:02x}{b:02x}"

    async def connect(self, websocket: WebSocket, user_id: Optional[str] = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.username_colors[websocket] = self._generate_pastel_color()
        if user_id:
            self.user_id_by_ws[websocket] = user_id

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.username_by_ws.pop(websocket, None)
        self.user_id_by_ws.pop(websocket, None)
        self.username_colors.pop(websocket, None)

    async def send_personal(self, websocket: WebSocket, payload: dict):
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    def add_language(self, lang_code: str):
        """Add language to global list"""
        if lang_code not in self.global_languages:
            self.global_languages.append(lang_code)

    def remove_language(self, lang_code: str):
        """Remove language from global list"""
        if lang_code in self.global_languages:
            self.global_languages.remove(lang_code)

    def get_languages(self) -> list[str]:
        """Get global language list"""
        return self.global_languages

    def set_username(self, websocket: WebSocket, username: str):
        self.username_by_ws[websocket] = username

    def get_username(self, websocket: WebSocket) -> Optional[str]:
        return self.username_by_ws.get(websocket)

    def get_user_color(self, websocket: WebSocket) -> Optional[str]:
        return self.username_colors.get(websocket)

    def get_active_users(self) -> list[dict]:
        """Get list of active users with names"""
        users = []
        for ws, username in self.username_by_ws.items():
            if ws in self.active_connections:
                users.append({
                    "username": username,
                    "color": self.username_colors.get(ws, "#e0e0e0")
                })
        return users

    def translator(self, target: str) -> GoogleTranslator:
        key = target.lower()
        tr = self.translator_cache.get(key)
        if tr is None:
            tr = GoogleTranslator(source="auto", target=key)
            self.translator_cache[key] = tr
        return tr

    async def broadcast_language_update(self):
        """Broadcast current global language list to all connected users"""
        payload = {
            "type": "language_update",
            "languages": self.global_languages
        }
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Failed to send language update: {e}")
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_users_update(self):
        """Broadcast current active users list to all connected users"""
        payload = {
            "type": "users_update",
            "users": self.get_active_users()
        }
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Failed to send users update: {e}")
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_translated(self, original: str, sender_name: str, sender_ws: WebSocket, message_id: Optional[str] = None):
        """Broadcast message with translations in all global languages"""
        global_langs = self.get_languages()
        sender_color = self.get_user_color(sender_ws) or "#e0e0e0"
        sender_id = self.get_user_id(sender_ws)

        if not global_langs:
            await self.send_personal(sender_ws, {"info": "No languages added yet. Add languages with '/add-lang <code-or-name>' to see translations."})
            return

        # Translate to all global languages (non-blocking with asyncio.to_thread)
        translations = {}
        for lang in global_langs:
            try:
                translated = await asyncio.to_thread(self.translator(lang).translate, original)
                translations[lang.upper()] = translated
            except Exception as e:
                logger.warning(f"Translation to {lang} failed: {e}")
                translations[lang.upper()] = f"[Translation error: {original}]"

        # Broadcast to all users with timestamp, but filter blocked users
        timestamp = datetime.now().isoformat()
        message_id = message_id or datetime.now().isoformat() + "-" + str(random.randint(1000, 9999))
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                # Check if this user has blocked the sender
                receiver_id = self.get_user_id(ws)
                if receiver_id and self.is_blocked(receiver_id, sender_name):
                    continue  # Skip sending to users who blocked the sender

                await ws.send_text(json.dumps({
                    "type": "chat",
                    "sender": sender_name,
                    "sender_id": sender_id,
                    "color": sender_color,
                    "original": original,
                    "translations": translations,
                    "timestamp": timestamp,
                    "message_id": message_id
                }, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Broadcast/send failed: {e}")
                stale.append(ws)
                try:
                    await ws.close()
                except Exception:
                    pass
        for ws in stale:
            self.disconnect(ws)

manager = ConnectionManager()

HELP = "Commands: '/name <your-name>' to set display name, '/add-lang <code-or-name>' to add a language (e.g., /add-lang fr, /add-lang spanish), '/remove-lang <code>' to remove a language."

# ------------------------------------------------------------------
# Authentication Endpoints
# ------------------------------------------------------------------
@app.post("/api/register")
async def register(user_data: UserRegister):
    """Register a new user"""
    users = load_json_file(USERS_FILE, {})
    
    if user_data.username in users:
        return JSONResponse({"error": "Username already exists"}, status_code=400)
    
    if len(user_data.username.strip()) < 3 or len(user_data.username) > MAX_USERNAME_LENGTH:
        return JSONResponse({"error": "Username must be 3-100 characters"}, status_code=400)
    
    if len(user_data.password) < 6 or len(user_data.password) > MAX_PASSWORD_LENGTH:
        return JSONResponse({"error": "Password must be 6-1000 characters"}, status_code=400)
    
    user_id = str(random.randint(100000, 999999)) + "-" + user_data.username
    users[user_data.username] = {
        "id": user_id,
        "username": user_data.username,
        "password_hash": get_password_hash(user_data.password),
        "email": user_data.email,
        "created_at": datetime.now().isoformat()
    }
    save_json_file(USERS_FILE, users)
    
    access_token = create_access_token(data={"sub": user_data.username, "user_id": user_id})
    return {"access_token": access_token, "token_type": "bearer", "username": user_data.username, "user_id": user_id}

@app.post("/api/login")
async def login(user_data: UserLogin):
    """Login and get access token"""
    users = load_json_file(USERS_FILE, {})
    
    if user_data.username not in users:
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    
    user = users[user_data.username]
    if not verify_password(user_data.password, user["password_hash"]):
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    
    access_token = create_access_token(data={"sub": user_data.username, "user_id": user["id"]})
    return {"access_token": access_token, "token_type": "bearer", "username": user_data.username, "user_id": user["id"]}

def get_current_user(authorization: str = Header(None)) -> dict:
    """Get current user from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    users = load_json_file(USERS_FILE, {})
    username = payload.get("sub")
    if username not in users:
        raise HTTPException(status_code=401, detail="User not found")
    
    return {"username": username, "user_id": payload.get("user_id"), "token": token}

@app.post("/api/block")
async def block_user(request: BlockRequest, current_user: dict = Depends(get_current_user)):
    """Block a user"""
    users = load_json_file(USERS_FILE, {})
    if request.username not in users:
        return JSONResponse({"error": "User not found"}, status_code=404)
    
    if request.username == current_user["username"]:
        return JSONResponse({"error": "Cannot block yourself"}, status_code=400)
    
    manager.block_user(current_user["user_id"], request.username)
    return {"message": f"User {request.username} has been blocked"}

@app.post("/api/unblock")
async def unblock_user(request: BlockRequest, current_user: dict = Depends(get_current_user)):
    """Unblock a user"""
    manager.unblock_user(current_user["user_id"], request.username)
    return {"message": f"User {request.username} has been unblocked"}

@app.get("/api/blocked")
async def get_blocked_users(current_user: dict = Depends(get_current_user)):
    """Get list of blocked users"""
    blocked = manager.blocked_users.get(current_user["user_id"], set())
    return {"blocked_users": list(blocked)}

@app.post("/api/report")
async def report_user(request: ReportRequest, current_user: dict = Depends(get_current_user)):
    """Report a user"""
    users = load_json_file(USERS_FILE, {})
    if request.username not in users:
        return JSONResponse({"error": "User not found"}, status_code=404)
    
    if request.username == current_user["username"]:
        return JSONResponse({"error": "Cannot report yourself"}, status_code=400)
    
    manager.add_report(current_user["user_id"], request.username, request.reason, request.message_id)
    return {"message": "Report submitted successfully"}

@app.get("/api/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    return {"username": current_user["username"], "user_id": current_user["user_id"]}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """WebSocket endpoint with optional authentication"""
    # Try to get token from query params or headers
    if not token:
        token = websocket.query_params.get("token")
    
    user_id = None
    if token:
        payload = verify_token(token)
        if payload:
            user_id = payload.get("user_id")
    
    await manager.connect(websocket, user_id)
    try:
        await manager.send_personal(websocket, {"info": "Welcome to Translation Chat!"})
        await manager.send_personal(websocket, {"info": HELP})
        # Send current global language list
        await manager.send_personal(websocket, {
            "type": "language_update",
            "languages": manager.get_languages()
        })
        # Send current active users list
        await manager.send_personal(websocket, {
            "type": "users_update",
            "users": manager.get_active_users()
        })

        while True:
            try:
                data = await websocket.receive_text()
            except Exception:
                break
            
            # Validate message size
            if len(data) > MAX_MESSAGE_LENGTH:
                await manager.send_personal(websocket, {"error": f"Message too long (max {MAX_MESSAGE_LENGTH} chars)"})
                continue

            # Name command (use authenticated username if available)
            if data.strip().lower().startswith("/name"):
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /name <your-name>"})
                    continue
                username = parts[1].strip()
                if not username:
                    await manager.send_personal(websocket, {"error": "Name cannot be empty"})
                    continue
                
                # If authenticated, use authenticated username, otherwise use provided name
                if user_id:
                    users = load_json_file(USERS_FILE, {})
                    for u, info in users.items():
                        if info["id"] == user_id:
                            username = u  # Use registered username
                            break
                
                manager.set_username(websocket, username)
                await manager.send_personal(websocket, {"info": f"Your name is now '{username}'"})
                await manager.broadcast_users_update()
                continue

            # Block command
            if data.strip().lower().startswith("/block"):
                if not user_id:
                    await manager.send_personal(websocket, {"error": "Authentication required. Please login first."})
                    continue
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /block <username>"})
                    continue
                username_to_block = parts[1].strip()
                manager.block_user(user_id, username_to_block)
                await manager.send_personal(websocket, {"info": f"User '{username_to_block}' has been blocked"})
                continue

            # Unblock command
            if data.strip().lower().startswith("/unblock"):
                if not user_id:
                    await manager.send_personal(websocket, {"error": "Authentication required. Please login first."})
                    continue
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /unblock <username>"})
                    continue
                username_to_unblock = parts[1].strip()
                manager.unblock_user(user_id, username_to_unblock)
                await manager.send_personal(websocket, {"info": f"User '{username_to_unblock}' has been unblocked"})
                continue

            # Report command
            if data.strip().lower().startswith("/report"):
                if not user_id:
                    await manager.send_personal(websocket, {"error": "Authentication required. Please login first."})
                    continue
                parts = data.split(maxsplit=2)
                if len(parts) < 3:
                    await manager.send_personal(websocket, {"error": "Usage: /report <username> <reason>"})
                    continue
                username_to_report = parts[1].strip()
                reason = parts[2].strip()
                manager.add_report(user_id, username_to_report, reason)
                await manager.send_personal(websocket, {"info": f"User '{username_to_report}' has been reported"})
                continue

            # Add language command
            if data.strip().lower().startswith("/add-lang"):
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /add-lang <code-or-name>"})
                    continue
                lang = normalize_lang(parts[1])
                if not lang:
                    await manager.send_personal(websocket, {"error": "Unknown language"})
                    continue
                if len(manager.get_languages()) >= MAX_LANGUAGES:
                    await manager.send_personal(websocket, {"error": f"Max {MAX_LANGUAGES} languages allowed"})
                    continue
                manager.add_language(lang)
                await manager.broadcast_language_update()
                continue

            # Remove language command
            if data.strip().lower().startswith("/remove-lang"):
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /remove-lang <code-or-name>"})
                    continue
                lang = normalize_lang(parts[1])
                if not lang:
                    await manager.send_personal(websocket, {"error": "Unknown language"})
                    continue
                manager.remove_language(lang)
                await manager.broadcast_language_update()
                continue

            # Broadcast translated to everyone, each in their chosen language
            sender_name = manager.get_username(websocket) or "Anonymous"
            await manager.broadcast_translated(original=data, sender_name=sender_name, sender_ws=websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # Broadcast updated user list
        await manager.broadcast_users_update()