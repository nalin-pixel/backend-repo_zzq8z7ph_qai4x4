import os
import time
import secrets
import hashlib
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import create_document, get_documents, db

app = FastAPI(title="Flex Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Utilities
# ----------------------
PASSWORD_SALT = os.getenv("PASSWORD_SALT", "flex-salt")
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return hashlib.sha256((PASSWORD_SALT + password).encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


# ----------------------
# Models
# ----------------------
class RegisterPayload(BaseModel):
    email: EmailStr
    display_name: str
    password: str


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class ScorePayload(BaseModel):
    value: int


# ----------------------
# Auth helpers
# ----------------------
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.replace("Bearer ", "").strip()
    sessions = get_documents("session", {"token": token}, limit=1)
    if not sessions:
        raise HTTPException(status_code=401, detail="Invalid session")

    sess = sessions[0]
    if int(sess.get("expires_at", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired")

    user_id = sess.get("user_id")
    users = get_documents("flexuser", {"_id": {"$eq": sess.get("user_id")}}, limit=1)
    # Fallback if _id stored as str
    if not users:
        users = get_documents("flexuser", {"_id": user_id}, limit=1)
    if not users:
        # try email if stored
        if sess.get("email"):
            users = get_documents("flexuser", {"email": sess.get("email")}, limit=1)
    if not users:
        raise HTTPException(status_code=401, detail="User not found")

    user = users[0]
    # Remove sensitive fields
    user.pop("password_hash", None)
    return user


# ----------------------
# Routes
# ----------------------
@app.get("/")
def read_root():
    return {"message": "Flex backend running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from Flex API!"}


@app.post("/auth/register")
def register(payload: RegisterPayload):
    # Check duplicate
    existing = get_documents("flexuser", {"email": payload.email}, limit=1)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = {
        "email": str(payload.email),
        "display_name": payload.display_name.strip(),
        "password_hash": hash_password(payload.password),
        "avatar": None,
        "high_score": 0,
        "is_active": True,
    }
    user_id = create_document("flexuser", user_doc)

    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    create_document("session", {
        "user_id": user_id,
        "token": token,
        "email": str(payload.email),
        "expires_at": expires_at,
    })

    return {"token": token, "user": {"_id": user_id, "email": payload.email, "display_name": payload.display_name, "high_score": 0}}


@app.post("/auth/login")
def login(payload: LoginPayload):
    users = get_documents("flexuser", {"email": payload.email}, limit=1)
    if not users:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = users[0]

    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    create_document("session", {
        "user_id": str(user.get("_id")),
        "token": token,
        "email": user.get("email"),
        "expires_at": expires_at,
    })

    # Hide sensitive fields
    user_resp = {
        "_id": str(user.get("_id")),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "high_score": user.get("high_score", 0),
        "avatar": user.get("avatar"),
    }

    return {"token": token, "user": user_resp}


@app.get("/me")
async def me(user=Depends(get_current_user)):
    return {"user": user}


@app.post("/scores")
async def submit_score(payload: ScorePayload, user=Depends(get_current_user)):
    score_value = int(payload.value)
    if score_value < 0:
        raise HTTPException(status_code=400, detail="Score must be >= 0")

    # Save score document
    create_document("score", {
        "user_id": str(user.get("_id")),
        "display_name": user.get("display_name"),
        "value": score_value,
    })
    return {"status": "ok"}


@app.get("/scores/top")
def top_scores(limit: int = 10):
    # Get top scores by value desc (since helper lacks sort, we sort in Python)
    docs = get_documents("score", {})
    docs_sorted = sorted(docs, key=lambda d: int(d.get("value", 0)), reverse=True)[:limit]
    # Serialize
    result = [
        {
            "display_name": d.get("display_name", "Player"),
            "value": int(d.get("value", 0)),
        }
        for d in docs_sorted
    ]
    return {"scores": result}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = getattr(db, "name", "✅ Connected")
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
