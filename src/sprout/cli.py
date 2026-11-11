"""sprout serve | sprout import FILE.json"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="sprout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    i = sub.add_parser("import", help="load a family's history from a JSON file (docs/import.md)")
    i.add_argument("file", type=Path)
    i.add_argument("--family-id", type=int, help="import into this existing family instead of creating one")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run(
            "sprout.web:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    elif args.cmd == "import":
        from sprout.config import from_env
        from sprout.importer import import_file

        result = import_file(from_env(), args.file, args.family_id)
        print(result)
        sys.exit(0)
