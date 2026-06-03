"""Entry point used by PyInstaller when building ``txt2img-backend.exe``.

Mirrors ``services/vectorizer-api/backend_entry.py``: pass the FastAPI
``app`` object directly to ``uvicorn.run`` so PyInstaller can statically
follow the reference and bundle the whole ``app`` package — no string-based
import lookup, no risk of missing ``--hidden-import`` flags.

Usage from source::

    python txt2img_entry.py --host 127.0.0.1 --port 9001

Usage as a frozen binary (Windows)::

    txt2img-backend.exe --host 127.0.0.1 --port 9001
"""
from __future__ import annotations

import argparse

import uvicorn

from app.main import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="txt2img API backend launcher")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--log-level", default="info")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
