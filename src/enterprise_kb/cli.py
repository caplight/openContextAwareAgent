"""CLI 入口：提供 ingest（建索引）等命令。"""

from __future__ import annotations

import argparse

from enterprise_kb.embed import index_chunks
from enterprise_kb.ingest import load_and_split


def _cmd_ingest() -> int:
    chunks = load_and_split()
    if not chunks:
        print("data/docs 下没有可摄入的文档")
        return 1
    n = index_chunks(chunks)
    print(f"已索引 {n} 个 chunks")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="enterprise-kb")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="摄入 data/docs 下文档并建索引")

    args = parser.parse_args()
    if args.cmd == "ingest":
        return _cmd_ingest()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
