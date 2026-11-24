"""python -m eap.cli run dev | run heldout | gate dev | evals | report | serve | mcp"""

from __future__ import annotations

import argparse
import json
import sys

from . import config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eap")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run every design on a split")
    r.add_argument("split", choices=["dev", "heldout"])
    r.add_argument("--workers", type=int, default=3)
    g = sub.add_parser("gate", help="exit 1 if the platform fails a gate on a split")
    g.add_argument("split", choices=["dev", "heldout"])
    sub.add_parser("evals", help="run the eval gate for the candidate models and print the verdicts")
    sub.add_parser("report", help="regenerate REPORT.md, the README block, the dashboard data and the ISMS control list")
    s = sub.add_parser("serve", help="run the API on a small simulated world")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("mcp", help="serve the platform's tools over MCP (stdio)")
    args = p.parse_args(argv)

    if args.cmd == "run":
        from .lab import study

        if args.split == "heldout":
            try:
                res = study.run_heldout_once(args.workers)
            except study.HeldOutLocked as e:
                print(e, file=sys.stderr)
                return 3
        else:
            res = study.run_split("dev", args.workers)
            study.write("dev", res)
        m = res["designs"]["platform"]
        print(f"{args.split}: p95 tenant-month error {m['tenant_month_error_p95']:.3f}, analyst min/1k {m['analyst_minutes_per_1k']:.2f}, gates pass: {res['gates']['platform_pass']}")
        return 0
    if args.cmd == "gate":
        path = config.REPORTS / f"{args.split}.json"
        res = json.loads(path.read_text(encoding="utf-8"))
        rows = res["gates"]["platform"]
        for x in rows:
            print(f"{'pass' if x['pass'] else 'FAIL'}  {x['gate']}: {x['value']} ({x['kind']} {x['limit']})")
        return 0 if all(x["pass"] for x in rows) else 1
    if args.cmd == "evals":
        from .evals.suite import run_gate

        res = run_gate("balanced", list(config.designs()["model_swap"]))
        for name, c in res["candidates"].items():
            print(f"{name}: {c['verdict']}" + (f" on {', '.join(c['blocked_on'])}" if c["blocked_on"] else ""))
        return 0
    if args.cmd == "report":
        from .lab.report import write_all

        for path in write_all():
            print(f"wrote {path.relative_to(config.ROOT)}")
        return 0
    if args.cmd == "serve":
        import uvicorn

        from .service.api import create_demo_app

        uvicorn.run(create_demo_app(), host="127.0.0.1", port=args.port)
        return 0
    if args.cmd == "mcp":
        from .agents.mcp_server import serve_stdio

        serve_stdio()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
