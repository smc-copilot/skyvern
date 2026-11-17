"""Machine-readable PR-00 error codes."""

from __future__ import annotations


class EnterpriseError(Exception):
    """Process-level failure with a stable error_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
