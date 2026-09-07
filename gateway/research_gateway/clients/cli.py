"""research-gateway CLI: the same five requests plus status/health, as JSON on stdout.

  python3 -m research_gateway.clients.cli find "management practices" --kind article --domain management
  python3 -m research_gateway.clients.cli resolve doi:10.1038/nature12373
  python3 -m research_gateway.clients.cli enrich doi:10.1038/nature12373 --what citations
  python3 -m research_gateway.clients.cli fetch doi:10.7910/DVN/OY6CBK
  python3 -m research_gateway.clients.cli fetch doi:10.7910/DVN/OY6CBK --params '{"file_id": 900, "download": true}' --out wms.csv
  python3 -m research_gateway.clients.cli data fred --params '{"series": "GDP"}'
  python3 -m research_gateway.clients.cli status | health
"""
from __future__ import annotations

import argparse
import json
import sys

from .http_client import from_env


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="research-gateway", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--domain", default=None)
        p.add_argument("--commercial", action="store_true")
        p.add_argument("--accept-per-item", action="store_true")
        p.add_argument("--topic", default=None)
        p.add_argument("--async", dest="async_", action="store_true", help="return the job id instead of waiting")

    p = sub.add_parser("find"); p.add_argument("query"); p.add_argument("--kind", choices=["article", "dataset"])
    p.add_argument("--limit", type=int, default=20); p.add_argument("--year-from", type=int); p.add_argument("--published-after"); common(p)
    p = sub.add_parser("resolve"); p.add_argument("identity"); common(p)
    p = sub.add_parser("enrich"); p.add_argument("identity"); p.add_argument("--what", required=True); common(p)
    p = sub.add_parser("fetch"); p.add_argument("target"); p.add_argument("--params", default="{}"); p.add_argument("--out"); common(p)
    p = sub.add_parser("data"); p.add_argument("source"); p.add_argument("--params", required=True); common(p)
    sub.add_parser("status"); sub.add_parser("health"); p = sub.add_parser("job"); p.add_argument("id", type=int)
    return ap


def payload_from(args: argparse.Namespace) -> dict:
    p = {"domain": args.domain, "commercial": args.commercial, "accept_per_item": args.accept_per_item, "topic_id": args.topic}
    if args.cmd == "find":
        p.update(query=args.query, kind=args.kind, limit=args.limit, year_from=args.year_from, published_after=args.published_after)
    elif args.cmd == "resolve":
        p.update(identity=args.identity)
    elif args.cmd == "enrich":
        p.update(identity=args.identity, what=args.what)
    elif args.cmd == "fetch":
        p.update(target=args.target, params=json.loads(args.params))
    elif args.cmd == "data":
        p.update(source=args.source, params=json.loads(args.params))
    return {k: v for k, v in p.items() if v not in (None, False)}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = from_env()
    if args.cmd == "status":
        out = client.status()
    elif args.cmd == "health":
        out = client.health()
    elif args.cmd == "job":
        out = client.job(args.id)
    else:
        rt = args.cmd
        out = client._call("POST", f"/v1/{rt}?async=1" if args.async_ else f"/v1/{rt}", payload_from(args))
    if isinstance(out.get("content"), (bytes, bytearray)):
        if args.cmd == "fetch" and args.out:
            with open(args.out, "wb") as f:
                f.write(out["content"])
            out = {"written": args.out, "bytes": len(out["content"]), "content_type": out.get("content_type")}
        else:
            out = {"content_bytes": len(out["content"]), "content_type": out.get("content_type"), "hint": "use --out FILE to save it"}
    json.dump(out, sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")
    return 1 if out.get("capability_fact", "").startswith("gateway_") else 0


if __name__ == "__main__":
    sys.exit(main())
