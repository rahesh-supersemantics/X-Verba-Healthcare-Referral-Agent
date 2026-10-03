"""
Entry point for the X-Verba Healthcare Referral Agent API.

    uvicorn main:app --reload
    python main.py
"""

import os

from backend.app import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("XVERBA_HOST", "127.0.0.1"),
        port=int(os.environ.get("XVERBA_PORT", "8000")),
    )
