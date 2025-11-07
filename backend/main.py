from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from deep_translator import GoogleTranslator
import logging
import json
import random
import os
from datetime import datetime
from typing import Optional

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

        translated = GoogleTranslator(source=src, target=tgt).translate(text)
        return {"source": src, "target": tgt, "original": text, "translated": translated}
    except Exception as e:
        logger.error(f"/translate error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ------------------------------------------------------------------
# WebSocket translation chat (per-user target language)
# ------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.global_languages: list[str] = []
        self.username_by_ws: dict[WebSocket, str] = {}
        self.username_colors: dict[WebSocket, str] = {}
        self.translator_cache: dict[str, GoogleTranslator] = {}

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

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.username_colors[websocket] = self._generate_pastel_color()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.username_by_ws.pop(websocket, None)
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

    async def broadcast_translated(self, original: str, sender_name: str, sender_ws: WebSocket):
        """Broadcast message with translations in all global languages"""
        global_langs = self.get_languages()
        sender_color = self.get_user_color(sender_ws) or "#e0e0e0"

        if not global_langs:
            await self.send_personal(sender_ws, {"info": "No languages added yet. Add languages with '/add-lang <code-or-name>' to see translations."})
            return

        # Translate to all global languages
        translations = {}
        for lang in global_langs:
            try:
                translated = self.translator(lang).translate(original)
                translations[lang.upper()] = translated
            except Exception as e:
                logger.warning(f"Translation to {lang} failed: {e}")
                translations[lang.upper()] = f"[Translation error: {original}]"

        # Broadcast to all users with timestamp
        timestamp = datetime.now().isoformat()
        stale: list[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(json.dumps({
                    "type": "chat",
                    "sender": sender_name,
                    "color": sender_color,
                    "original": original,
                    "translations": translations,
                    "timestamp": timestamp
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
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
            data = await websocket.receive_text()

            # Name command
            if data.strip().lower().startswith("/name"):
                parts = data.split(maxsplit=1)
                if len(parts) != 2:
                    await manager.send_personal(websocket, {"error": "Usage: /name <your-name>"})
                    continue
                username = parts[1].strip()
                if not username:
                    await manager.send_personal(websocket, {"error": "Name cannot be empty"})
                    continue
                manager.set_username(websocket, username)
                await manager.send_personal(websocket, {"info": f"Your name is now '{username}'"})
                await manager.broadcast_users_update()
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