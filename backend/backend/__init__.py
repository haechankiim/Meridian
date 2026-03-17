"""Compatibility package for running Meridian from the backend directory.

This lets commands such as:
    python -m pytest tests/test_app.py
    uvicorn backend.app.main:app

work even when the current working directory is `/.../Meridian/backend`.
"""

from pathlib import Path

# Expose the parent backend directory as the package search path so
# `backend.app`, `backend.api`, etc. resolve consistently from both the
# repository root and the backend subdirectory.
__path__ = [str(Path(__file__).resolve().parent.parent)]
