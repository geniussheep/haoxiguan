#!/usr/bin/env bash
cd "$(dirname "$0")"
bash "./scripts/sync_from_server.sh"
echo ""
echo "同步完毕！按任意键退出窗口..."
read -n 1
