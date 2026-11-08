#!/usr/bin/env bash
# 启动 demo：Streamlit Q&A 前端（端口 8501，配合 cloudflared 隧道对外暴露）
#
# ⚠️ 关键：必须去掉 ALL_PROXY/all_proxy（socks 代理会让 litellm/httpx 报
#    "Unknown scheme for proxy URL"），保留 http 代理（deepseek/brave 需要走它）。
#
# 用法：bash scripts/start_demo.sh
set -euo pipefail

cd "$(dirname "$0")/.."   # 切到 demo 项目根目录

# 加载 .env 里的 key 到环境变量。
# ⚠️ litellm 的 deepseek provider 只读 DEEPSEEK_API_KEY 环境变量（get_secret_str），
#   不读 litellm.deepseek_key 属性，也不读 ChatLiteLLM 的 api_key 字段。
#   streamlit 进程若不显式 export，会间歇性读不到 key → 401 governor。
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# 停掉旧 8501 进程（SIGTERM 对 streamlit 无效，直接 SIGKILL）
OLD_PID=$(ss -tlnp 2>/dev/null | grep ':8501 ' | grep -oP 'pid=\K[0-9]+' | head -1 || true)
if [ -n "$OLD_PID" ]; then
  echo "停掉旧 8501 进程 (PID=$OLD_PID)"
  kill -9 "$OLD_PID" 2>/dev/null || true
  sleep 2
fi

# 去掉 socks 代理，保留 http 代理
env -u ALL_PROXY -u all_proxy \
  nohup /root/.venvs/enterprise-kb/bin/streamlit run frontend/streamlit_app.py \
    --server.headless true --server.port 8501 --server.address 0.0.0.0 \
    > /tmp/streamlit_8501.log 2>&1 &

echo "新 PID=$!"
sleep 8
curl -s -o /dev/null -w "健康检查 HTTP %{http_code}\n" http://localhost:8501/
