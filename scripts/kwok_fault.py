#!/usr/bin/env python3
"""KWOK 故障注入 / 检测 / 恢复统一 CLI。

Phase 3（AI 故障检测）的集群故障操作入口。封装 9 种常见故障的
「注入 → 状态采集 → 恢复」闭环，demo 模式批量跑一遍并输出结构化
样本集（JSON），可直接喂给故障检测模型做训练/评测。

依赖：仅标准库 + `kubectl`（需已配置 KWOK 集群 kubeconfig）。

用法：
    python kwok_fault.py list                 # 列出支持的故障类型
    python kwok_fault.py inject oomkilled     # 注入单个故障
    python kwok_fault.py recover oomkilled    # 恢复单个故障
    python kwok_fault.py check --all          # 检测当前集群异常
    python kwok_fault.py demo                 # 批量演示所有故障
    python kwok_fault.py demo -o samples.json # 输出结构化样本集

设计要点：
    - 统一机制：故障 = 注入 Stage（simulate:<type> label）+ 恢复 Stage
      （label 去掉自动接管），见 docs/kwok.md。
    - Unschedulable 是调度层故障，不走 Stage（会跟 pod-ready 竞争），
      用「无 nodeName + 超大资源」天然触发调度失败。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 故障清单
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fault:
    key: str
    kind: str  # "node" | "pod"
    label: str | None  # simulate label value；Unschedulable 为 None（天然触发）
    desc: str
    # 检测时关注的 condition / 特征
    detect: dict[str, Any] = field(default_factory=dict)
    natural: bool = False  # True = 天然触发，不走 label


FAULTS: dict[str, Fault] = {
    # ---- Node 级 ----
    "not-ready": Fault(
        "not-ready", "node", "not-ready",
        "节点失联（Ready=False，心跳停更，kube-controller-manager 判定失联）",
        detect={"condition": "Ready", "expect": "False"},
    ),
    "memory-pressure": Fault(
        "memory-pressure", "node", "memory-pressure",
        "内存压力（MemoryPressure=True）",
        detect={"condition": "MemoryPressure", "expect": "True"},
    ),
    "disk-pressure": Fault(
        "disk-pressure", "node", "disk-pressure",
        "磁盘压力（DiskPressure=True）",
        detect={"condition": "DiskPressure", "expect": "True"},
    ),
    "pid-pressure": Fault(
        "pid-pressure", "node", "pid-pressure",
        "PID 压力（PIDPressure=True）",
        detect={"condition": "PIDPressure", "expect": "True"},
    ),
    "network-unavailable": Fault(
        "network-unavailable", "node", "network-unavailable",
        "网络不可用（NetworkUnavailable=True）",
        detect={"condition": "NetworkUnavailable", "expect": "True"},
    ),
    # ---- Pod 级（运行时故障）----
    "crashloop": Fault(
        "crashloop", "pod", "crashloop",
        "CrashLoopBackOff（容器反复崩溃重启）",
        detect={"reason": "CrashLoopBackOff"},
    ),
    "oomkilled": Fault(
        "oomkilled", "pod", "oomkilled",
        "OOMKilled（内存超限被杀，exitCode 137）",
        detect={"reason": "OOMKilled"},
    ),
    "imagepullbackoff": Fault(
        "imagepullbackoff", "pod", "imagepullbackoff",
        "ImagePullBackOff（镜像拉取失败）",
        detect={"reason": "ImagePullBackOff"},
    ),
    "evicted": Fault(
        "evicted", "pod", "evicted",
        "Evicted（被驱逐）",
        detect={"reason": "Evicted"},
    ),
    # ---- Pod 级（调度层故障，天然触发）----
    "unschedulable": Fault(
        "unschedulable", "pod", None,
        "Unschedulable（资源不足无法调度）",
        detect={"reason": "Unschedulable"},
        natural=True,
    ),
}

# 默认操作对象
DEFAULT_NODE = "fake-node-2"
PROBE_POD = "kwok-fault-probe"          # 运行时故障的探针 pod
UNSCHED_POD = "kwok-fault-unsched"       # Unschedulable 的专用 pod
PROBE_POD_MANIFEST = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {"name": PROBE_POD},
    "spec": {
        "nodeName": "fake-node-0",
        "containers": [
            {"name": "fake-container", "image": "fake-image"},
        ],
    },
}
UNSCHED_POD_MANIFEST = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {"name": UNSCHED_POD},
    "spec": {
        "containers": [
            {
                "name": "fake-container",
                "image": "fake-image",
                "resources": {
                    "requests": {"cpu": "100", "memory": "4Gi"},
                },
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# kubectl 封装
# ---------------------------------------------------------------------------


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """跑 kubectl，静默 stderr，失败时返回非零（check=False 不抛）。"""
    return subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _apply(manifest: dict[str, Any]) -> None:
    """kubectl apply 一个 manifest（从 stdin）。"""
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
    )


def _delete(kind: str, name: str) -> None:
    _run(["delete", kind, name, "--force", "--grace-period=0"])


def _label(kind: str, name: str, kv: str) -> None:
    _run(["label", kind, name, kv])


def _get_json(kind: str, name: str) -> dict[str, Any] | None:
    r = _run(["get", kind, name, "-o", "json"])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _wait(seconds: float) -> None:
    time.sleep(seconds)


def _wait_for(predicate, timeout: float = 15.0, interval: float = 0.5) -> bool:
    """轮询直到 predicate 返回 True 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# 故障操作
# ---------------------------------------------------------------------------


def ensure_probe_pod() -> None:
    """确保探针 pod 存在且 Running（运行时故障的操作对象）。"""
    if _get_json("pod", PROBE_POD) is None:
        _apply(PROBE_POD_MANIFEST)
        _wait(2)


def ensure_unsched_pod() -> None:
    """确保 Unschedulable 专用 pod 存在（天然触发，会一直 Pending）。"""
    if _get_json("pod", UNSCHED_POD) is None:
        _apply(UNSCHED_POD_MANIFEST)
        _wait(3)


def _target(fault: Fault) -> tuple[str, str]:
    """返回 (kind, name) 操作对象。"""
    if fault.natural:
        return "pod", UNSCHED_POD
    if fault.kind == "node":
        return "node", DEFAULT_NODE
    return "pod", PROBE_POD


def inject(key: str, timeout: float = 15.0) -> dict[str, Any]:
    """注入故障，轮询等待故障激活后返回状态快照。"""
    fault = FAULTS[key]
    if fault.natural:
        ensure_unsched_pod()
    else:
        kind, name = _target(fault)
        if fault.kind == "pod":
            ensure_probe_pod()
        _label(kind, name, f"simulate={fault.label}")
    # 轮询等待故障激活（而非固定 sleep，KWOK Stage 异步 reconcile 有抖动）
    _wait_for(lambda: is_fault_active(fault, snapshot(fault)), timeout)
    return snapshot(fault)


def recover(key: str, timeout: float = 15.0) -> dict[str, Any]:
    """恢复故障，轮询等待故障消除后返回状态快照。"""
    fault = FAULTS[key]
    if fault.natural:
        # Unschedulable 无恢复 Stage，直接删 pod 即「恢复」
        _delete("pod", UNSCHED_POD)
    else:
        kind, name = _target(fault)
        _label(kind, name, "simulate-")
    _wait_for(lambda: not is_fault_active(fault, snapshot(fault)), timeout)
    return snapshot(fault)


# ---------------------------------------------------------------------------
# 状态采集
# ---------------------------------------------------------------------------


def _node_snapshot(name: str) -> dict[str, Any] | None:
    obj = _get_json("node", name)
    if obj is None:
        return None
    conds = {
        c.get("type"): c.get("status")
        for c in obj.get("status", {}).get("conditions", [])
    }
    return {"name": name, "conditions": conds}


def _pod_snapshot(name: str) -> dict[str, Any] | None:
    obj = _get_json("pod", name)
    if obj is None:
        return None
    status = obj.get("status", {})
    containers = status.get("containerStatuses", [])
    # 提取容器状态摘要（state 里的 waiting/terminated reason）
    summary = []
    for c in containers:
        st = c.get("state", {})
        entry = {"name": c.get("name"), "ready": c.get("ready"), "restartCount": c.get("restartCount", 0)}
        for sname, sval in st.items():
            entry["state"] = sname
            entry["reason"] = sval.get("reason", "")
        last = c.get("lastState", {})
        for sname, sval in last.items():
            entry["lastState"] = sname
            entry["lastReason"] = sval.get("reason", "")
        summary.append(entry)
    # 提取 condition 的 reason（如 Unschedulable 在 PodScheduled condition 里，
    # 不在顶层 status.reason）
    cond_reasons = {
        c.get("type"): c.get("reason")
        for c in status.get("conditions", [])
        if c.get("reason")
    }
    return {
        "name": name,
        "phase": status.get("phase"),
        "reason": status.get("reason"),
        "message": status.get("message"),
        "ready": _ready(status),
        "containers": summary,
        "conditionReasons": cond_reasons,
    }


def _ready(status: dict[str, Any]) -> str:
    """计算 pod 的 ready 显示（如 0/1、1/1）。"""
    total = len(status.get("containerStatuses", []))
    if total == 0:
        return "0/0"
    ready = sum(
        1 for c in status.get("containerStatuses", []) if c.get("ready")
    )
    return f"{ready}/{total}"


def snapshot(fault: Fault) -> dict[str, Any]:
    """采集单个故障当前状态快照（供检测/样本集）。"""
    kind, name = _target(fault)
    if fault.kind == "node":
        return _node_snapshot(name) or {"name": name, "conditions": {}}
    return _pod_snapshot(name) or {"name": name, "phase": "NotFound"}


def is_fault_active(fault: Fault, snap: dict[str, Any]) -> bool:
    """根据快照判断故障是否处于激活状态（用于 check）。"""
    d = fault.detect
    if "condition" in d:
        return snap.get("conditions", {}).get(d["condition"]) == d["expect"]
    if "reason" in d:
        want = d["reason"]
        # pod 的 reason 可能出现在：顶层 status.reason、容器 state.reason / lastReason、
        # 或 condition 的 reason（如 Unschedulable 在 PodScheduled condition）
        if snap.get("reason") == want:
            return True
        for c in snap.get("containers", []):
            if c.get("reason") == want or c.get("lastReason") == want:
                return True
        if want in snap.get("conditionReasons", {}).values():
            return True
        return False
    return False


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


def cmd_list() -> None:
    print("支持的故障类型：\n")
    print(f'{"key":<22} {"层级":<6} 说明')
    print("-" * 70)
    for key in FAULTS:
        f = FAULTS[key]
        tag = "天然" if f.natural else f.label
        print(f"{key:<22} {f.kind:<6} {f.desc}  [label={tag}]")


def cmd_check(show_all: bool) -> None:
    """扫描当前集群，列出处于异常状态的故障。"""
    found = False
    for key, fault in FAULTS.items():
        snap = snapshot(fault)
        active = is_fault_active(fault, snap)
        if active or show_all:
            mark = "⚠️  ACTIVE" if active else "✅  normal"
            print(f"{key:<22} {mark}")
            if active:
                found = True
    if not found:
        print("当前集群无激活故障。")
    else:
        print(f"\n共 {sum(1 for k, f in FAULTS.items() if is_fault_active(f, snapshot(f)))} 个激活故障。")


def cmd_demo(output: str | None) -> None:
    """批量演示：逐个故障「注入 → 采集 → 恢复 → 采集」，输出样本集。"""
    samples: list[dict[str, Any]] = []
    print("=== KWOK 故障注入 demo ===\n")
    for key, fault in FAULTS.items():
        print(f"[{key}] 注入中...")
        injected = inject(key)
        active = is_fault_active(fault, injected)
        status = "✅" if active else "❌"
        print(f"  {status} 注入后: {_fmt(fault, injected)}")

        recovered = recover(key)
        reactivated = is_fault_active(fault, recovered)
        rstatus = "✅ 已恢复" if not reactivated else "❌ 仍异常"
        print(f"  {rstatus}: {_fmt(fault, recovered)}\n")

        samples.append({
            "fault": key,
            "level": fault.kind,
            "desc": fault.desc,
            "injected": injected,
            "recovered": recovered,
            "inject_ok": active,
            "recover_ok": not reactivated,
        })

    ok = sum(1 for s in samples if s["inject_ok"] and s["recover_ok"])
    print(f"结果：{ok}/{len(samples)} 个故障注入+恢复闭环通过。")

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            json.dump(samples, fh, ensure_ascii=False, indent=2)
        print(f"样本集已写入 {output}")


def _fmt(fault: Fault, snap: dict[str, Any]) -> str:
    """人类可读的单行状态摘要。"""
    if fault.kind == "node":
        conds = snap.get("conditions", {})
        return ", ".join(f"{k}={v}" for k, v in conds.items()) or "（无 conditions）"
    return (
        f"phase={snap.get('phase')} ready={snap.get('ready')} "
        f"reason={snap.get('reason')} containers={snap.get('containers')}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KWOK 故障注入/检测/恢复 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出支持的故障类型")

    p_inject = sub.add_parser("inject", help="注入故障")
    p_inject.add_argument("fault", choices=list(FAULTS))
    p_inject.add_argument("--timeout", type=float, default=15.0)

    p_recover = sub.add_parser("recover", help="恢复故障")
    p_recover.add_argument("fault", choices=list(FAULTS))
    p_recover.add_argument("--timeout", type=float, default=15.0)

    p_check = sub.add_parser("check", help="检测当前集群异常")
    p_check.add_argument("--all", action="store_true", help="显示所有故障状态（含正常）")

    p_demo = sub.add_parser("demo", help="批量演示所有故障")
    p_demo.add_argument("-o", "--output", help="输出样本集 JSON 路径")

    args = p.parse_args(argv)

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "inject":
        snap = inject(args.fault, args.timeout)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    elif args.cmd == "recover":
        snap = recover(args.fault, args.timeout)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        cmd_check(args.all)
    elif args.cmd == "demo":
        cmd_demo(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
