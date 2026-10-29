import hashlib
import json
import secrets
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or utcnow()).isoformat().replace("+00:00", "Z")


def token():
    return secrets.token_hex(24)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Problem(Exception):
    def __init__(self, status, code, message, details=None, retryable=False):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        self.retryable = retryable
        super().__init__(message)

    def body(self, request_id):
        return dict(code=self.code, message=self.message[:2000], details=self.details[:100],
                    request_id=request_id, retryable=self.retryable)
