"""python -m smartagri.research_api [--host 127.0.0.1] [--port 8100]"""
from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser(prog="smartagri.research_api")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    a = p.parse_args()
    import uvicorn

    from .app import create_app
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
