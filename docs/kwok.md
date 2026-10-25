# KWOK — Simulated Cluster Backend

> Phase 3 的集群状态源。KWOK（**K**ubernetes **W**ith**O**ut **K**ubelet）是官方 SIG 项目，
> 用空壳 node / pod 在几秒内模拟出一个几千节点的活集群，专门用来做调度、扩缩容和故障演练。

## 为什么选它

Phase 3 要做一个「DevOps 助手」，贴近求职方向（AI 故障检测、预测性维护）。它需要一个**会动的集群状态源**，而不是静态文档。选型时对比过：

| 方案 | 特点 | 结论 |
|---|---|---|
| **KWOK** | 官方 SIG，秒级模拟大量 node，能注入故障，兼容 kubectl | ✅ 采用 |
| kube-emulator | 纯 fake API server，没有「活」状态 | 太假，故障模拟弱 |
| LocalStack / MiniStack | AWS 模拟器，EKS 特定 | 更重，偏离通用 K8s |

关键优势：**低资源**。我们这台 VM 只有 4 核 / 7.7G，KWOK 整个集群才 ~470MB 内存，跑得毫无压力。

## 集群搭建

工具装到 `/usr/local/bin`（下载要挂代理 `HTTP_PROXY=http://192.168.23.1:7890`）：

```bash
# kwokctl v0.8.0 + kubectl v1.37.1
kwokctl create cluster --runtime binary --name kwok
```

**用 binary runtime** 是刻意的——它直接跑 etcd / kube-apiserver / controller-manager / scheduler 的二进制，**完全不碰 docker 镜像**。这避开了之前 Langfuse 踩过的镜像 DNS 污染坑。

起来的 5 个组件（内存占用）：

| 组件 | 内存 |
|---|---|
| etcd | 42M |
| kube-apiserver | 247M |
| kwok-controller（`--manage-all-nodes=true`）| 48M |
| kube-controller-manager | 86M |
| kube-scheduler | 45M |

kubeconfig 在 `/root/.kube/config`，二进制和配置在 `/root/.kwok/clusters/kwok/`。

## 模拟 node / pod

KWOK v0.8 没有 `create node` 子命令了，直接 `kubectl apply` 一个带 `kwok.x-k8s.io/node: fake` annotation 的 Node 即可，kwok-controller 会自动接管并维护 heartbeat：

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Node
metadata:
  name: fake-node-0
  annotations:
    kwok.x-k8s.io/node: fake
  labels:
    type: kwok
spec:
  taints:
  - effect: NoSchedule
    key: kwok.x-k8s.io/node
    value: fake
EOF
```

我们建了 3 个异构 node（32 / 16 / 8 CPU），然后 `kubectl apply` 一个 `replicas: 6` 的 deployment，6 个 pod 顺利调度到 3 个 node 上，全 Running。

## Stage CRD

KWOK 用 **Stage** 来描述资源的「生命周期阶段」——node 从初始化到心跳，pod 从 Pending 到 Running 到删除。默认这些 Stage 是内联在 config 里的，为了动态故障注入，我们把它们转成了 **CRD**：

- 12 个 CRD，API group `kwok.x-k8s.io`（v1alpha1）
- 5 个默认 Stage：`node-initialize`、`node-heartbeat-with-lease`、`pod-ready`、`pod-complete`、`pod-delete`
- kwok-controller 重启时加 `--enable-crds=Stage`

> 约束：`--config` 内联 Stage 和 `--enable-crds=Stage` **不能同时用**（会报 `Stage already exists in --config`），所以删掉 `--config` 走纯 CRD。

## 故障注入（完整故障类型清单）

这是「AI 故障检测」场景的核心。直接 `kubectl patch` 模拟故障是**行不通**的——`--manage-all-nodes=true` 会让 kwok 持续把状态拉回健康。正确姿势是用 Stage。

### 统一机制：label 触发 + 恢复 Stage 自动接管

每个故障一个「注入 Stage」（匹配 `simulate: <type>` label），一个「恢复 Stage」（匹配 label 已去掉的异常资源）。注入加 label，恢复去 label，构成可逆闭环：

```bash
kubectl label <resource> <name> simulate=<type>   # ① 注入：加 label → Stage 触发故障
kubectl get <resource> <name>                     # ② 检测：直接看到异常状态
kubectl label <resource> <name> simulate-         # ③ 恢复：去 label → 恢复 Stage 自动拉回健康
```

### 完整清单（9 种故障，全部验证通过）

| 层级 | 故障 | label value | 状态特征 | 注入方式 |
|---|---|---|---|---|
| Node | NotReady | `not-ready` | Ready=False, 心跳停更 | Stage |
| Node | MemoryPressure | `memory-pressure` | MemoryPressure=True | Stage |
| Node | DiskPressure | `disk-pressure` | DiskPressure=True | Stage |
| Node | PIDPressure | `pid-pressure` | PIDPressure=True | Stage |
| Node | NetworkUnavailable | `network-unavailable` | NetworkUnavailable=True | Stage |
| Pod | CrashLoopBackOff | `crashloop` | restartCount 137, waiting | Stage |
| Pod | OOMKilled | `oomkilled` | exitCode 137, lastState terminated | Stage |
| Pod | ImagePullBackOff | `imagepullbackoff` | phase Pending, waiting | Stage |
| Pod | Evicted | `evicted` | phase Failed, reason Evicted | Stage |
| Pod | Unschedulable | （无） | PodScheduled=False | **天然**（见下） |

### 代表性 Stage：node 故障

node 的 5 种故障 Stage 结构完全一致，只有 `matchLabels` 的 label value 和 condition type 不同。以 MemoryPressure 为例：

```yaml
apiVersion: kwok.x-k8s.io/v1alpha1
kind: Stage
metadata:
  name: node-memory-pressure-simulate
spec:
  resourceRef:
    apiGroup: v1
    kind: Node
  selector:
    matchLabels:
      simulate: memory-pressure
  next:
    statusTemplate: |
      {{ $now := Now }}
      conditions:
      - type: MemoryPressure
        status: "True"
        reason: "KubeletHasInsufficientMemory"
        lastHeartbeatTime: {{ $now | Quote }}
        lastTransitionTime: {{ $now | Quote }}
```

NotReady 最特殊：它把 `Ready` 置 False 后，默认的 `node-heartbeat-with-lease`（要求 Ready=True）停止更新 lease，kube-controller-manager 判定节点彻底失联，condition 显示 `Unknown / NodeStatusUnknown`，比单纯 NotReady 更真实。

### 代表性 Stage：pod 故障

pod 故障 Stage 匹配 `simulate: <type>` label + 特定 phase，把容器状态改成对应故障。以 OOMKilled 为例（关键差异在 `lastState.terminated` 的 exitCode 137）：

```yaml
apiVersion: kwok.x-k8s.io/v1alpha1
kind: Stage
metadata:
  name: pod-oomkilled-simulate
spec:
  resourceRef:
    apiGroup: v1
    kind: Pod
  selector:
    matchLabels:
      simulate: oomkilled
    matchExpressions:
    - jq: { key: .status.phase, operator: In, values: ["Running"] }
  next:
    statusTemplate: |
      {{ $now := Now }}
      phase: Running
      containerStatuses:
      - image: "fake-image"
        name: "fake-container"
        ready: false
        restartCount: 3
        lastState:
          terminated:
            exitCode: 137
            reason: OOMKilled
        state:
          waiting:
            reason: CrashLoopBackOff
      conditions:
      - type: Ready
        status: "False"
        reason: "ContainersNotReady"
        lastTransitionTime: {{ $now | Quote }}
```

### 恢复 Stage（node + pod 各一个，通用）

**pod-recover**：匹配「phase 非正常 + Ready 不为 True + simulate label 已去掉」的 pod，拉回 Running。关键技巧是用 `DoesNotExist` 匹配「label 已去掉」，去 label 后自动接管，无需手动 patch：

```yaml
apiVersion: kwok.x-k8s.io/v1alpha1
kind: Stage
metadata:
  name: pod-recover
spec:
  resourceRef:
    apiGroup: v1
    kind: Pod
  selector:
    matchExpressions:
    - jq: { key: .status.phase, operator: In, values: ["Running", "Pending", "Failed"] }
    - jq:
        key: .status.conditions.[] | select(.type == "Ready") | .status
        operator: NotIn
        values: ["True"]
    - jq: { key: .metadata.labels.simulate, operator: DoesNotExist }
  next:
    statusTemplate: |
      {{ $now := Now }}
      phase: Running
      reason: ""
      message: ""
      containerStatuses:
      {{ range .spec.containers }}
      - image: {{ .image | Quote }}
        name: {{ .name | Quote }}
        ready: true
        restartCount: 0
        state:
          running:
            startedAt: {{ $now | Quote }}
      {{ end }}
      conditions:
      - type: Ready
        status: "True"
        lastTransitionTime: {{ $now | Quote }}
      - type: ContainersReady
        status: "True"
        lastTransitionTime: {{ $now | Quote }}
      - type: PodScheduled
        status: "True"
        lastTransitionTime: {{ $now | Quote }}
```

**node-recover**：匹配「simulate label 已去掉 + 有非 Ready 的 True condition」的 node，把所有压力/网络 condition 置 False、Ready 置 True。

### Unschedulable：唯一的「天然」故障

Unschedulable 是**调度层故障**，本质不同于运行时故障（crashloop/oomkilled 等）。它没法用「先 Running 再 label 触发」的套路——一旦把 phase 改成 Pending，会跟默认的 `pod-ready` Stage（Pending → Running）反复竞争。正确做法是**天然触发**：不指定 `nodeName`，请求超出所有节点容量的资源，让 scheduler 真实调度失败：

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: demo-unschedulable
spec:
  containers:
  - name: c
    image: fake-image
    resources:
      requests:
        cpu: "100"        # 远超所有 fake node 容量
        memory: "4Gi"
EOF
# 结果：phase=Pending, reason=Unschedulable, PodScheduled=False
```

> 我们的 fake node 都带 `NoSchedule` taint，所以不指定 nodeName 的 pod 天然就无法调度，Unschedulable 几乎必然触发。

## 踩坑记录

1. **`selector.matchExpressions[].key` 是 jq 表达式，不是 label key。** 想匹配 label 却写了 `key: simulate`，被当成 jq 函数调用 → 报 `function not defined: simulate/0`，更糟的是直接 **panic（nil 指针）把 kwok-controller 崩了**。label 匹配请用 `selector.matchLabels`，或用 `matchExpressions` + `jq: {key: .metadata.labels.simulate, ...}`。

2. **故障 Stage 会被默认 Stage 覆盖。** 直接 patch node/pod 状态无效，必须用 Stage 定义。

3. **Stage 没有全局优先级。** 执行顺序靠 selector 链式控制（一个 Stage 的 selector 匹配上一个 Stage 的 `next` 状态）；相同 selector 的多个 Stage 用 `weight` 字段控制概率。

4. **恢复需要手动触发。** 去掉故障 label 后 `node-initialize` 不会自动重新评估，要 patch 一下触发。

5. **pod 故障（CrashLoopBackOff）已跑通，恢复要用「恢复 Stage」而非手动 patch。** 早期（10-21）手动带 `nodeName` 的 pod 卡 Pending，当时是 Stage CRD 刚补全、controller 未稳定，3 天后复测已正常注入 CrashLoopBackOff。真正要小心的坑在**恢复**：手动 patch 想把 pod 拉回 Running 时，`pod-ready` 会重新用 `PodIPsWith` 生成新 podIP，与残留的旧 podIP 冲突，报 `may specify no more than one IP for each IP family`。正确姿势是建一个「恢复 Stage」（见上），用 `DoesNotExist` 匹配去掉 label 的 pod 自动恢复，别手动 patch。

6. **恢复 Stage 要清 `reason`/`message` 残留。** merge patch 只覆盖 statusTemplate 里写了的字段。evicted 恢复后 phase 变回 Running 了，但 `reason: Evicted` 残留，`kubectl get pod` 的 STATUS 列仍显示 Evicted。解法：恢复 Stage 的 statusTemplate 里显式写 `reason: ""` 和 `message: ""` 清空。同理 `Ready` condition 的旧 reason 也会残留，属纯展示层问题。

7. **Unschedulable 别用 Stage，会跟 pod-ready 竞争。** 把 phase 改成 Pending 会触发默认 `pod-ready`（Pending → Running）反复拉回，导致状态抖动。用「无 nodeName + 超大资源」天然触发（见上）。

8. **bash `local` 连环赋值是陷阱。** 写 `local fault=$1 name="t-$fault"` 时，`$fault` 在赋值前就被展开成空值，`name` 变成 `t-`。必须拆两行：`local fault=$1` 然后 `local name="t-$fault"`。否则测试脚本里 pod 名全错，`kubectl` 静默失败（配 `2>/dev/null` 更难排查）。

## 常用命令

```bash
kwokctl get clusters                                   # 查集群
kubectl get nodes -o wide                              # 查 node 状态
kubectl get stages                                     # 查 Stage CRD
kwokctl delete cluster --name kwok                     # 删集群

# 重启 kwok-controller（改参数后需手动重启）
cd /root/.kwok/clusters/kwok && nohup ./bin/kwok-controller \
  --manage-all-nodes=true --kubeconfig=./kubeconfig.yaml \
  --tls-cert-file=./pki/admin.crt --tls-private-key-file=./pki/admin.key \
  --node-ip= --node-name=localhost --node-port=32763 \
  --server-address=0.0.0.0:32763 --node-lease-duration-seconds=200 \
  --enable-crds=Stage > ./logs/kwok-controller.log 2>&1 &
```

故障/恢复 Stage 文件统一放在 `/tmp/kwok-stages/`：

```
node-not-ready.yaml          # NotReady
node-memory-pressure.yaml    # MemoryPressure
node-disk-pressure.yaml      # DiskPressure
node-pid-pressure.yaml       # PIDPressure
node-network-unavailable.yaml# NetworkUnavailable
node-recover.yaml            # node 通用恢复
pod-crashloop.yaml           # CrashLoopBackOff
pod-oomkilled.yaml           # OOMKilled
pod-imagepullbackoff.yaml    # ImagePullBackOff
pod-evicted.yaml             # Evicted
pod-recover.yaml             # pod 通用恢复
```

（Unschedulable 无 Stage 文件，天然触发。）
