#!/usr/bin/env bash
set -euo pipefail

HOME="${HOME:-/Users/sheep.yang}"
LOCAL_DIR="/Users/sheep.yang/Documents/Sheep/好习惯/好习惯打卡网站"
SSH_KEY="${HOME}/.ssh/tx-mq"
REMOTE_HOST="ubuntu@106.52.154.64"
REMOTE_DIR="/opt/xiguan"
LOG_FILE="$LOCAL_DIR/sync.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== 开始同步云端好习惯数据到本地 ==="

# 0. 触发云端 SQLite WAL 刷盘，确保所有新打卡数据全部落入 habit.db
ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    "$REMOTE_HOST" "sudo -u www-data sqlite3 $REMOTE_DIR/habit.db 'PRAGMA wal_checkpoint(TRUNCATE);' 2>/dev/null || true"

# 1. 备份本地上一次的数据库文件（最多保留一次上次的备份，直接覆盖 .bak）
if [[ -f "$LOCAL_DIR/habit.db" ]]; then
    cp -f "$LOCAL_DIR/habit.db" "$LOCAL_DIR/habit.db.bak"
    log "已备份本地上一次数据库为: habit.db.bak"
fi

if [[ -f "$LOCAL_DIR/data.json" ]]; then
    cp -f "$LOCAL_DIR/data.json" "$LOCAL_DIR/data.json.bak"
    log "已备份本地上一次数据为: data.json.bak"
fi

# 2. 从云端下载最新数据到临时文件
scp -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    "$REMOTE_HOST:$REMOTE_DIR/habit.db" "$LOCAL_DIR/habit.db.tmp"

scp -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    "$REMOTE_HOST:$REMOTE_DIR/data.json" "$LOCAL_DIR/data.json.tmp"

# 3. 校验并原子覆盖更新
if [[ -s "$LOCAL_DIR/habit.db.tmp" ]]; then
    mv -f "$LOCAL_DIR/habit.db.tmp" "$LOCAL_DIR/habit.db"
    log "habit.db 已更新覆盖为云端最新版本"
else
    rm -f "$LOCAL_DIR/habit.db.tmp"
    log "错误: 下载的 habit.db 为空，已终止替换"
    exit 1
fi

if [[ -s "$LOCAL_DIR/data.json.tmp" ]]; then
    mv -f "$LOCAL_DIR/data.json.tmp" "$LOCAL_DIR/data.json"
    log "data.json 已更新覆盖为云端最新版本"
fi

log "=== 数据同步完成 ==="
