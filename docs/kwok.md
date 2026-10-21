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

## 故障注入（node NotReady 完整闭环）

这是「AI 故障检测」场景的核心。直接 `kubectl patch` 模拟故障是**行不通**的——`--manage-all-nodes=true` 会让 kwok 持续把状态拉回健康。正确姿势是用 Stage：

```yaml
apiVersion: kwok.x-k8s.io/v1alpha1
kind: Stage
metadata:
  name: node-not-ready-simulate
spec:
  resourceRef:
    apiGroup: v1
    kind: Node
  selector:
    matchLabels:
      simulate: not-ready
  next:
    statusTemplate: |
      {{ $now := Now }}
      conditions:
      - type: Ready
        status: "False"
        reason: "KubeletNotReady"
        lastHeartbeatTime: {{ $now | Quote }}
        lastTransitionTime: {{ $now | Quote }}
      # MemoryPressure / DiskPressure / PIDPressure 同理置 False
```

三步走，形成一个漂亮的可逆闭环：

```bash
kubectl label node fake-node-2 simulate=not-ready   # ① 注入：节点变 NotReady
kubectl get nodes                                   # ② 检测：直接看到 NotReady
kubectl label node fake-node-2 simulate-            # ③ 恢复：去 label
kubectl patch node fake-node-2 --type=merge -p '{"status":{"conditions":[{"type":"Ready","status":"True","reason":"KubeletReady"}]}}'
```

注入后节点 condition 是 `Unknown / NodeStatusUnknown`，比单纯的 NotReady 更真实——故障 Stage 把 Ready 置 False 后，默认的 `node-heartbeat-with-lease`（要求 Ready=True）停止更新 lease，kube-controller-manager 判定节点彻底失联。

## 踩坑记录

1. **`selector.matchExpressions[].key` 是 jq 表达式，不是 label key。** 想匹配 label 却写了 `key: simulate`，被当成 jq 函数调用 → 报 `function not defined: simulate/0`，更糟的是直接 **panic（nil 指针）把 kwok-controller 崩了**。label 匹配请用 `selector.matchLabels`，或用 `matchExpressions` + `jq: {key: .metadata.labels.simulate, ...}`。

2. **故障 Stage 会被默认 Stage 覆盖。** 直接 patch node/pod 状态无效，必须用 Stage 定义。

3. **Stage 没有全局优先级。** 执行顺序靠 selector 链式控制（一个 Stage 的 selector 匹配上一个 Stage 的 `next` 状态）；相同 selector 的多个 Stage 用 `weight` 字段控制概率。

4. **恢复需要手动触发。** 去掉故障 label 后 `node-initialize` 不会自动重新评估，要 patch 一下触发。

5. **pod 故障（CrashLoopBackOff）待解决。** 手动 `kubectl apply` 带 `nodeName` 的 pod 卡在 Pending，没被 `pod-ready` 处理；deployment 创建的 pod 则正常。疑似手动指定 nodeName 不走 scheduler binding。node 故障是核心，已跑通；pod 这个留待下轮。

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

故障 Stage 示例文件：`/tmp/stage-node-failure.yaml`、`/tmp/stage-pod-crashloop.yaml`。
