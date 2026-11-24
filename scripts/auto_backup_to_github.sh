#!/usr/bin/env bash
# ==========================================================
# 好习惯魔法存折 - 云端数据库自动备份至 GitHub 脚本
# 运行环境: 腾讯云服务器 (Ubuntu)
# 调度周期: 每日定时执行 (建议 02:00)
# ==========================================================
set -euo pipefail

APP_DIR="/opt/xiguan"
LOG_FILE="/var/log/xiguan/backup.log"
SSH_KEY="/home/ubuntu/.ssh/id_ed25519_github_habit"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | sudo tee -a "$LOG_FILE" >/dev/null
}

sudo mkdir -p "$(dirname "$LOG_FILE")"
sudo mkdir -p "$APP_DIR/scripts"

log "=== 开始执行数据库自动备份流水线 ==="

# 1. 触发 SQLite WAL 刷盘，确保所有最新打卡数据全量落入 habit.db
if [[ -f "$APP_DIR/habit.db" ]]; then
    sudo -u www-data sqlite3 "$APP_DIR/habit.db" 'PRAGMA wal_checkpoint(TRUNCATE);' 2>/dev/null || true
    log "SQLite WAL 检查点刷盘完成。"
fi

# 2. 配置 Git 访问
cd "$APP_DIR"
export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

# 3. 检查远程连接并拉取最新提交（避免远程有页面更新冲突）
if git remote get-url origin >/dev/null 2>&1; then
    log "同步远程代码最新变动（快进合并）..."
    git fetch origin main >> /tmp/git_backup.log 2>&1 || true
    git merge --ff-only origin/main >> /tmp/git_backup.log 2>&1 || true
fi

# 4. 检查 habit.db 或 data.json 是否有新数据
if git status --porcelain habit.db data.json 2>/dev/null | grep -q .; then
    log "检测到生产数据库有新数据，开始提交并推送至 GitHub..."
    git add habit.db data.json
    COMMIT_TIME=$(date '+%Y-%m-%d %H:%M:%S')
    git commit -m "backup(data): auto backup habit.db & data.json [$COMMIT_TIME]" >> /tmp/git_backup.log 2>&1
    git push origin main >> /tmp/git_backup.log 2>&1
    log "=== 数据库已成功推送到 GitHub main 分支！ ==="
else
    log "数据无实质变动，本次跳过提交。"
fi

# 5. 确保生产目录始终归属 www-data:www-data 守护进程
sudo chown -R www-data:www-data "$APP_DIR"
log "=== 备份流水线执行结束 ==="
