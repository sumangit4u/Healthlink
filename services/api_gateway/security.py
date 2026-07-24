"""
Lightweight security helpers for the api-gateway (Session 7 hardening).

- input validation (length + script/HTML injection)
- prompt-injection heuristics
- PII masking for logs
- a simple in-memory sliding-window rate limiter (per client, per replica)

These are intentionally dependency-free so the gateway image stays tiny.
"""
import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

# ---- Input validation ------------------------------------------------------

_SCRIPT_PATTERNS = [r"<script", r"javascript:", r"onclick=", r"onerror="]


def validate_user_input(user_input: str, min_length: int = 10, max_length: int = 5000) -> Tuple[bool, str]:
    """Validate a health-concern string. Returns (is_valid, error_message)."""
    if not user_input or not user_input.strip():
        return False, "Input is required"
    text_len = len(user_input.strip())
    if text_len < min_length:
        return False, f"Please provide more details (at least {min_length} characters)"
    if text_len > max_length:
        return False, f"Input must be no more than {max_length} characters"
    for pattern in _SCRIPT_PATTERNS:
        if re.search(pattern, user_input, re.IGNORECASE):
            return False, "Input contains potentially harmful content"
    return True, ""


# ---- Prompt-injection heuristics ------------------------------------------

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(the\s+)?(above|previous)",
    r"you\s+are\s+now\s+",
    r"system\s+prompt",
    r"reveal\s+your\s+(system\s+)?prompt",
    r"act\s+as\s+(a\s+)?(dan|developer\s+mode)",
]


def detect_prompt_injection(text: str) -> bool:
    """Return True if the text looks like a prompt-injection attempt."""
    return any(re.search(p, text, re.IGNORECASE) for p in _INJECTION_PATTERNS)


# ---- PII masking (for logs) -----------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\s-]?){9,15}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def mask_pii(text: str) -> str:
    """Mask emails, phone numbers, and SSNs so they never hit the logs."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _SSN_RE.sub("[SSN]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


# ---- Rate limiting (in-memory sliding window, per replica) ------------------

class RateLimiter:
    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, client_id: str) -> bool:
        now = time.time()
        hits = self._hits[client_id]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
