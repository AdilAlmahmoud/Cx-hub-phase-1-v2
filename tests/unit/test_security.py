"""Unit tests for security utilities."""
from datetime import timedelta
import pytest
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mysecret")
        assert hashed != "mysecret"

    def test_verify_correct_password(self):
        hashed = hash_password("mysecret")
        assert verify_password("mysecret", hashed) is True

    def test_reject_wrong_password(self):
        hashed = hash_password("mysecret")
        assert verify_password("wrong", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts are random


class TestJWT:
    def test_create_and_decode_token(self):
        token = create_access_token({"sub": "user-id", "tenant_id": "tenant-id"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-id"
        assert payload["tenant_id"] == "tenant-id"

    def test_expired_token_returns_none(self):
        token = create_access_token({"sub": "u"}, expires_delta=timedelta(seconds=-1))
        assert decode_access_token(token) is None

    def test_invalid_token_returns_none(self):
        assert decode_access_token("not.a.token") is None

    def test_tampered_token_returns_none(self):
        token = create_access_token({"sub": "u"})
        tampered = token[:-5] + "XXXXX"
        assert decode_access_token(tampered) is None
