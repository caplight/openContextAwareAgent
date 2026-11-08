#!/usr/bin/env bash
# auto_sync_web.sh: 监听本地前端目录，改动自动同步回 hgfs（debounce 2s）
# 用法：nohup bash scripts/auto_sync_web.sh > /tmp/auto_sync_web.log 2>&1 &
set -euo pipefail

LOCAL=/root/enterprise-kb-web
REMOTE=/mnt/hgfs/VMWareShare/remote_jobs_research/demo/web
LOG=/tmp/auto_sync_web.log

command -v inotifywait >/dev/null || { echo "缺少 inotify-tools"; exit 1; }

echo "[auto-sync] 启动：$LOCAL → $REMOTE"

# 首次全量同步（排除 node_modules/dist，--delete 保持本地为准）
rsync -a --delete --exclude node_modules --exclude dist "$LOCAL/" "$REMOTE/"
echo "[auto-sync] 初始同步完成"

while true; do
  inotifywait -r -q \
    -e modify -e create -e delete -e move \
    --exclude 'node_modules' --exclude 'dist' --exclude '.git' \
    "$LOCAL" 2>/dev/null
  sleep 2   # debounce，合并批量改动
  if rsync -a --delete --exclude node_modules --exclude dist "$LOCAL/" "$REMOTE/"; then
    echo "[auto-sync] $(date '+%H:%M:%S') 已同步"
  else
    echo "[auto-sync] $(date '+%H:%M:%S') 同步失败"
  fi
done
