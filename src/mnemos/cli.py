"""mnemosctl — command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from .core import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mnemosctl",
        description="Mnemos — context is a compiled artifact, not a concatenated string.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the localhost inspector UI + API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--embedder", default="hashing", choices=["hashing", "neural"])

    p_bench = sub.add_parser("bench", help="naive prompt vs compiled context benchmark")
    p_bench.add_argument("--budgets", default="800,1500,3000")
    p_bench.add_argument("--embedder", default="hashing", choices=["hashing", "neural"])
    p_bench.add_argument("--json", dest="json_path", default=None)

    p_ask = sub.add_parser("ask", help="compile context for one question and print it")
    p_ask.add_argument("query")
    p_ask.add_argument("--budget", type=int, default=800)
    p_ask.add_argument("--embedder", default="hashing", choices=["hashing", "neural"])
    p_ask.add_argument("--explain", action="store_true")

    args = parser.parse_args()

    match args.command:
        case "serve":
            import uvicorn

            from .app import create_app

            app = create_app(Settings(embedder=args.embedder))
            print(f"\n  Mnemos inspector → http://{args.host}:{args.port}\n", file=sys.stderr)
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")

        case "bench":
            from .bench import format_table, run

            results = run([int(b) for b in args.budgets.split(",")], args.embedder)
            print(format_table(results))
            if args.json_path:
                with open(args.json_path, "w", encoding="utf-8") as fh:
                    json.dump(results, fh, indent=2)

        case "ask":
            from .bench import SYSTEM_PROMPT, build_corpus, demo_principal
            from .compiler import Budgets, ContextCompiler, ContextRequest, SectionSpec
            from .retrieval import RetrievalEngine

            settings = Settings(embedder=args.embedder)
            store, embedder, tokenizer = build_corpus(settings)
            compiler = ContextCompiler(
                RetrievalEngine(store, embedder, tokenizer), embedder, tokenizer, settings
            )
            bundle = compiler.compile(
                ContextRequest(
                    principal=demo_principal(),
                    query=args.query,
                    budgets=Budgets(tokens=args.budget),
                    sections=[
                        SectionSpec("memory", floor_tokens=60,
                                    ceil_tokens=max(200, args.budget // 5), priority=10),
                        SectionSpec("documents", floor_tokens=0,
                                    ceil_tokens=args.budget, priority=5),
                    ],
                    system_prompt=SYSTEM_PROMPT,
                )
            )
            if args.explain:
                print(json.dumps(bundle.explain, indent=2))
            else:
                print(bundle.prompt)
                print(f"\n--- {bundle.digest} | {bundle.tokens_consumed}/{args.budget} tokens "
                      f"| {len(bundle.manifest)} sources | {bundle.latency_ms:.1f} ms ---")
            store.close()


if __name__ == "__main__":
    main()
