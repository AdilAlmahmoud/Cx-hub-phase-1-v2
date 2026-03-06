"""
Security utilities: password hashing and JWT.

Password hashing uses PBKDF2-HMAC-SHA256 (stdlib only).
JWT uses HS256 via stdlib (hmac + hashlib).
Both avoid broken C-extension dependencies in this environment.
In production Docker containers (which have proper libffi/cffi),
passlib[bcrypt] can be substituted for stronger bcrypt hashing.
"""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.config import settings

_ITERATIONS = 260_000  # OWASP recommended minimum for PBKDF2-SHA256


# ── Password hashing (PBKDF2-HMAC-SHA256) ────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    encoded = base64.b64encode(salt + dk).decode()
    return f"pbkdf2:sha256:{_ITERATIONS}${encoded}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its stored hash."""
    try:
        scheme, rest = hashed_password.split("$", 1)
        _, algo, iters_str = scheme.split(":")
        iters = int(iters_str)
        raw = base64.b64decode(rest)
        salt = raw[:16]
        stored_dk = raw[16:]
        dk = hashlib.pbkdf2_hmac(algo, plain_password.encode(), salt, iters)
        return hmac.compare_digest(dk, stored_dk)
    except Exception:
        return False


# ── JWT (pure-stdlib HS256) ───────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = int(expire.timestamp())

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps(to_encode).encode())
    signing_input = f"{header}.{payload}"
    signature = _b64url_encode(
        hmac.new(settings.SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
    )
    return f"{signing_input}.{signature}"


def decode_access_token(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = _b64url_encode(
            hmac.new(settings.SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected_sig, signature_b64):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            return None
        return payload
    except Exception:
        return None
