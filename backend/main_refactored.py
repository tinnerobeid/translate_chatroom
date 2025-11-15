"""
Translation Chat Backend - Main Application
Refactored with modular structure (routes, models, schemas)
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from deep_translator import GoogleTranslator
import asyncio
import os
import json
import random
import logging
from datetime import datetime
from typing import Optional

# Import routes
from app.routes import auth, moderation
from app.models import BlockRepository, UserRepository

# =====================================================================
# Logging Setup
# =====================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =====================================================================
# FastAPI App Setup
# =====================================================================
app = FastAPI(
    title="Translation Chat Backend",
    description="Real-time translation chat with user authentication",
    version="2.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # open for dev/testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# Static Files & Frontend Serving
# =====================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def read_root():
    """Serve the main frontend HTML"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend not found", "path": FRONTEND_DIR}

# =====================================================================
# Include Route Modules
# =====================================================================
app.include_router(auth.router)
app.include_router(moderation.router)

# =====================================================================
# Translation Utilities
# =====================================================================
_supported_langs_cache: Optional[dict[str, str]] = None

def get_supported_languages_dict() -> dict[str, str]:
    """Get supported languages mapping"""
    global _supported_langs_cache
    if _supported_langs_cache is not None:
        return _supported_langs_cache

    try:
        langs = GoogleTranslator.get_supported_languages(as_dict=True)
    except TypeError:
        langs = GoogleTranslator(source="auto", target="en").get_supported_languages(as_dict=True)

    _supported_langs_cache = {name.lower(): code for name, code in langs.items()}
    return _supported_langs_cache


def normalize_lang(user_input: Optional[str]) -> Optional[str]:
    """Normalize language name or code to ISO code"""
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

# =====================================================================
# Translation Endpoints
# =====================================================================
@app.get("/languages")
async def languages():
    """Get supported languages"""
    try:
        return {"supported_languages": get_supported_languages_dict()}
    except Exception as e:
        logger.error(f"/languages error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/translate")
async def translate_http(
    text: str = Query(..., description="Text to translate"),
    target: str = Query("fr", description="Target language code or name"),
    source: Optional[str] = Query(None, description="Optional source language")
):
    """Translate text to target language"""
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

        translated = await asyncio.to_thread(
            GoogleTranslator(source=src, target=tgt).translate, text
        )
        return {"source": src, "target": tgt, "original": text, "translated": translated}
    except Exception as e:
        logger.error(f"/translate error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# =====================================================================
# WebSocket Connection Manager
# =====================================================================
class ConnectionManager:
    """Manages WebSocket connections for real-time chat"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.global_languages: list[str] = []
        self.username_by_ws: dict[WebSocket, str] = {}
        self.user_id_by_ws: dict[WebSocket, str] = {}
        self.username_colors: dict[WebSocket, str] = {}
        self.translator_cache: dict[str, GoogleTranslator] = {}

    def _generate_pastel_color(self) -> str:
        """Generate random pastel color"""
        hue = random.randint(0, 360)
        saturation = random.randint(25, 45)
        lightness = random.randint(75, 90)

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

    def get_username(self, websocket: WebSocket) -> Optional[str]:
        return self.username_by_ws.get(websocket)

    def set_username(self, websocket: WebSocket, username: str):
        self.username_by_ws[websocket] = username

    def get_user_id(self, websocket: WebSocket) -> Optional[str]:
        return self.user_id_by_ws.get(websocket)

    def get_user_color(self, websocket: WebSocket) -> Optional[str]:
        return self.username_colors.get(websocket)

    def add_language(self, lang_code: str):
        if lang_code not in self.global_languages:
            self.global_languages.append(lang_code)

    def remove_language(self, lang_code: str):
        if lang_code in self.global_languages:
            self.global_languages.remove(lang_code)

    def get_languages(self) -> list[str]:
        return self.global_languages

    def get_active_users(self) -> list[dict]:
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
        """Broadcast language update to all clients"""
        payload = {"type": "language_update", "languages": self.global_languages}
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Broadcast failed: {e}")
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_users_update(self):
        """Broadcast users update to all clients"""
        payload = {"type": "users_update", "users": self.get_active_users()}
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Broadcast failed: {e}")
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_translated(self, original: str, sender_name: str, sender_ws: WebSocket):
        """Broadcast translated message to all clients"""
        global_langs = self.get_languages()
        sender_color = self.get_user_color(sender_ws) or "#e0e0e0"
        sender_id = self.get_user_id(sender_ws)

        if not global_langs:
            await self.send_personal(sender_ws, {
                "info": "No languages added yet. Add languages with '/add-lang <code-or-name>'"
            })
            return

        # Translate to all languages
        translations = {}
        for lang in global_langs:
            try:
                translated = await asyncio.to_thread(self.translator(lang).translate, original)
                translations[lang.upper()] = translated
            except Exception as e:
                logger.warning(f"Translation to {lang} failed: {e}")
                translations[lang.upper()] = f"[Translation error]"

        # Broadcast to all users
        timestamp = datetime.now().isoformat()
        message_id = f"{timestamp}-{random.randint(1000, 9999)}"
        stale: list[WebSocket] = []
        
        for ws in list(self.active_connections):
            try:
                receiver_id = self.get_user_id(ws)
                if receiver_id and BlockRepository.is_blocked(receiver_id, sender_name):
                    continue

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
                logger.warning(f"Broadcast failed: {e}")
                stale.append(ws)
        
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()

# =====================================================================
# WebSocket Endpoint
# =====================================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """WebSocket endpoint for real-time chat"""
    # Verify token
    if not token:
        token = websocket.query_params.get("token")
    
    user_id = None
    if token:
        from app.routes.auth import verify_token
        payload = verify_token(token)
        if payload:
            user_id = payload.get("user_id")
    
    await manager.connect(websocket, user_id)
    try:
        await manager.send_personal(websocket, {"info": "Welcome to Translation Chat!"})
        await manager.send_personal(websocket, {
            "info": "Commands: /name <name>, /add-lang <code>, /remove-lang <code>"
        })
        await manager.send_personal(websocket, {
            "type": "language_update",
            "languages": manager.get_languages()
        })
        await manager.send_personal(websocket, {
            "type": "users_update",
            "users": manager.get_active_users()
        })

        while True:
            try:
                data = await websocket.receive_text()
            except Exception:
                break

            # Process commands
            if data.strip().lower().startswith("/name"):
                parts = data.split(maxsplit=1)
                if len(parts) == 2:
                    username = parts[1].strip()
                    if user_id:
                        user = UserRepository.get_user_by_id(user_id)
                        if user:
                            username = user.username
                    manager.set_username(websocket, username)
                    await manager.send_personal(websocket, {"info": f"Your name: {username}"})
                    await manager.broadcast_users_update()

            elif data.strip().lower().startswith("/add-lang"):
                parts = data.split(maxsplit=1)
                if len(parts) == 2:
                    lang = normalize_lang(parts[1])
                    if lang:
                        manager.add_language(lang)
                        await manager.broadcast_language_update()

            elif data.strip().lower().startswith("/remove-lang"):
                parts = data.split(maxsplit=1)
                if len(parts) == 2:
                    lang = normalize_lang(parts[1])
                    if lang:
                        manager.remove_language(lang)
                        await manager.broadcast_language_update()

            else:
                sender_name = manager.get_username(websocket) or "Anonymous"
                await manager.broadcast_translated(data, sender_name, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast_users_update()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
