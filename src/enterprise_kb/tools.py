"""DevOps 助手工具集：查集群（kubectl）+ 查文档（向量库）。

Phase 3 的 agent 工具池。设计原则：

- **薄封装**：k8s 工具只做「拼 kubectl 命令 → 返回原始文本」，不做状态解析，
  让 agent 自己解读（ReAct 模式，工具保持单一职责）。
- **查文档复用现有检索链路**：`kb_search` 直接复用 Phase 2 的
  retrieve_hybrid_candidates + rerank，返回片段（不生成答案，方案 A）。

工具清单：
    k8s_get      查资源当前状态（get -o wide）
    k8s_describe 查资源事件/配置（describe）
    k8s_logs     查容器日志（logs，含 --previous）
    k8s_events   查事件时间线（get events）
    kb_search    查知识库文档（hybrid + rerank）
"""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool

from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# 返回给 agent 的最大字符数（防止 describe/logs 超大输出撑爆上下文）
_MAX_OUTPUT_CHARS = 8000


def _run_kubectl(args: list[str]) -> str:
    """执行 kubectl，返回 stdout 文本；失败时返回错误信息（不抛异常）。"""
    try:
        r = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "[错误] kubectl 命令超时（30s）"
    except FileNotFoundError:
        return "[错误] 未找到 kubectl，请确认已安装并在 PATH 中"

    out = r.stdout or r.stderr or ""
    if r.returncode != 0:
        out = f"[错误] kubectl 退出码 {r.returncode}：\n{out}"
    return _truncate(out)


def _truncate(text: str) -> str:
    """超长输出截断并提示（保留末尾，events/logs 最新信息通常在末尾）。"""
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return (
        f"[输出过长，已截断（原 {len(text)} 字符，仅保留首尾）]\n"
        f"{text[: _MAX_OUTPUT_CHARS // 2]}\n...\n{text[-_MAX_OUTPUT_CHARS // 2 :]}"
    )


def _ns_args(namespace: str | None, kind: str) -> list[str]:
    """构造 -n namespace 参数（node 等集群级资源不加）。"""
    if kind == "node" or namespace is None:
        return []
    return ["-n", namespace]


# ---------------------------------------------------------------------------
# 4 个 K8s 取证工具
# ---------------------------------------------------------------------------


@tool
def k8s_get(kind: str, name: str, namespace: str = "default") -> str:
    """查询 Kubernetes 资源当前状态（如 pod/node/deployment/service 等）。

    用于回答「这个资源现在是什么状态」：phase、READY、RESTARTS、AGE 等关键列。
    想看具体事件/原因用 k8s_describe，想看容器日志用 k8s_logs。

    Args:
        kind: 资源类型（小写，如 pod、node、deployment、service、statefulset）
        name: 资源名
        namespace: 命名空间，默认 default（node 等集群级资源忽略此参数）
    """
    args = ["get", kind, name, "-o", "wide", *_ns_args(namespace, kind)]
    return _run_kubectl(args)


@tool
def k8s_describe(kind: str, name: str, namespace: str = "default") -> str:
    """查看 Kubernetes 资源的详细描述（Events、Conditions、探针失败、调度失败原因等）。

    用于排查「为什么是这个状态」：describe 会列出最近事件流（如 Liveness probe
    failed、Back-off restarting、调度失败的具体原因）。是 root cause 分析的主力工具。

    Args:
        kind: 资源类型（小写）
        name: 资源名
        namespace: 命名空间，默认 default
    """
    args = ["describe", kind, name, *_ns_args(namespace, kind)]
    return _run_kubectl(args)


@tool
def k8s_logs(pod: str, container: str = "", namespace: str = "default", tail: int = 100, previous: bool = False) -> str:
    """查看容器日志。

    用于排查容器内部发生了什么。崩溃的 pod 加 previous=true 可拿到崩溃前最后输出
    （OOMKilled / panic / 依赖连不上 等根因常藏在这里）。

    Args:
        pod: pod 名
        container: 容器名（多容器 pod 时指定；单容器可留空）
        namespace: 命名空间，默认 default
        tail: 只取最后 N 行，默认 100
        previous: True 表示取上一次（崩溃前）的日志
    """
    args = ["logs", pod, "-n", namespace, f"--tail={tail}"]
    if container:
        args += ["-c", container]
    if previous:
        args += ["--previous"]
    return _run_kubectl(args)


@tool
def k8s_events(namespace: str = "default", involved_name: str = "") -> str:
    """查询命名空间内的 Kubernetes 事件（按时间排序）。

    用于看「按时间发生了什么」：调度、拉镜像、探针、驱逐等事件的时间线，
    是重建故障过程的重要工具。

    Args:
        namespace: 命名空间，默认 default
        involved_name: 只看涉及某个资源的事件（如某个 pod 名），留空则查全部
    """
    args = ["get", "events", "-n", namespace, "--sort-by=.lastTimestamp"]
    if involved_name:
        args += ["--field-selector", f"involvedObject.name={involved_name}"]
    return _run_kubectl(args)


# ---------------------------------------------------------------------------
# 1 个文档检索工具
# ---------------------------------------------------------------------------


@tool
def kb_search(query: str, top_k: int = 5) -> str:
    """检索企业知识库文档（K8s / AWS 等官方文档语料）。

    用于回答「怎么做 / 最佳实践是什么」这类知识性问题（如「OOM 了怎么调 limits」）。
    返回最相关的文档片段（带编号），供后续综合判断；不生成最终答案。

    Args:
        query: 检索查询（自然语言问题或关键词）
        top_k: 返回片段数，默认 5
    """
    from enterprise_kb.rerank import rerank
    from enterprise_kb.retrieve import retrieve_hybrid_candidates

    candidates = retrieve_hybrid_candidates(query)
    contexts = rerank(query, candidates, top_k)
    if not contexts:
        return "[提示] 知识库为空或未建索引（先运行 `kb ingest` 摄入文档）。"
    return "\n\n---\n\n".join(f"[{i + 1}] {ctx}" for i, ctx in enumerate(contexts))


# 全部工具（agent 的工具池）
ALL_TOOLS = [k8s_get, k8s_describe, k8s_logs, k8s_events, kb_search]
