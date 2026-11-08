"""框架无关的 Kubernetes 取证核心逻辑。

从原 LangChain 工具里抽出来的纯函数，供 MCP server / LangChain tool / CLI 等多处复用。
设计原则：**薄封装**——只做「拼 kubectl 命令 → 返回原始文本」，不做状态解析，
让上层 agent 自己解读（工具保持单一职责）。
"""

from __future__ import annotations

import subprocess

# 返回给上层（agent / 客户端）的最大字符数（防止 describe/logs 超大输出撑爆上下文）
_MAX_OUTPUT_CHARS = 8000


def run_kubectl(args: list[str]) -> str:
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
    return truncate(out)


def truncate(text: str) -> str:
    """超长输出截断并提示（保留末尾，events/logs 最新信息通常在末尾）。"""
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return (
        f"[输出过长，已截断（原 {len(text)} 字符，仅保留首尾）]\n"
        f"{text[: _MAX_OUTPUT_CHARS // 2]}\n...\n{text[-_MAX_OUTPUT_CHARS // 2 :]}"
    )


def ns_args(namespace: str | None, kind: str) -> list[str]:
    """构造 -n namespace 参数（node 等集群级资源不加）。"""
    if kind == "node" or namespace is None:
        return []
    return ["-n", namespace]


def k8s_get(kind: str, name: str, namespace: str = "default") -> str:
    """查询 Kubernetes 资源当前状态（如 pod/node/deployment/service 等）。

    用于回答「这个资源现在是什么状态」：phase、READY、RESTARTS、AGE 等关键列。
    想看具体事件/原因用 k8s_describe，想看容器日志用 k8s_logs。

    Args:
        kind: 资源类型（小写，如 pod、node、deployment、service、statefulset）
        name: 资源名
        namespace: 命名空间，默认 default（node 等集群级资源忽略此参数）
    """
    args = ["get", kind, name, "-o", "wide", *ns_args(namespace, kind)]
    return run_kubectl(args)


def k8s_describe(kind: str, name: str, namespace: str = "default") -> str:
    """查看 Kubernetes 资源的详细描述（Events、Conditions、探针失败、调度失败原因等）。

    用于排查「为什么是这个状态」：describe 会列出最近事件流（如 Liveness probe
    failed、Back-off restarting、调度失败的具体原因）。是 root cause 分析的主力工具。

    Args:
        kind: 资源类型（小写）
        name: 资源名
        namespace: 命名空间，默认 default
    """
    args = ["describe", kind, name, *ns_args(namespace, kind)]
    return run_kubectl(args)


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
    return run_kubectl(args)


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
    return run_kubectl(args)
