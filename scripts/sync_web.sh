#!/usr/bin/env bash
# 同步前端源码：本地磁盘（/root/enterprise-kb-web，有 node_modules）→ hgfs（demo/web，源码仓库）
# 原因：hgfs（VMWare 共享目录）不支持 symlink，node_modules 无法在 hgfs 安装，
#       故开发/构建在本地磁盘，源码通过本脚本同步回 hgfs 供 git 跟踪 + 爸爸猫在 Windows 查看。
set -euo pipefail

LOCAL=/root/enterprise-kb-web
REMOTE=/mnt/hgfs/VMWareShare/remote_jobs_research/demo/web

rsync -a --delete \
  --exclude node_modules \
  --exclude dist \
  "$LOCAL/" "$REMOTE/"

echo "✅ 已同步 $LOCAL → $REMOTE（排除 node_modules/dist）"
