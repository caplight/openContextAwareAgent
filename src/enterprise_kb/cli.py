"""CLI 入口：ingest（建索引）、agent（DevOps 助手）等命令。"""

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


def _cmd_agent(question: str) -> int:
    from enterprise_kb.agent import ask

    result = ask(question)
    print(result["answer"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="enterprise-kb")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="摄入 data/docs 下文档并建索引")

    p_agent = sub.add_parser("agent", help="DevOps 助手（诊断集群 / 查文档）")
    p_agent.add_argument("question", help="要问的问题，如「payment-svc 一直重启为什么」")

    args = parser.parse_args()
    if args.cmd == "ingest":
        return _cmd_ingest()
    if args.cmd == "agent":
        return _cmd_agent(args.question)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
