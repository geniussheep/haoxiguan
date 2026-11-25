#!/usr/bin/env bash
# ==========================================================
# 好习惯魔法存折 - 本地安全备份与多重容灾归档流水线
# 运行环境: 腾讯云服务器 (Ubuntu)
# ==========================================================
set -euo pipefail

APP_DIR="/opt/xiguan"
BACKUP_DIR="$APP_DIR/backups"
LOG_FILE="/var/log/xiguan/backup.log"
SSH_KEY="/home/ubuntu/.ssh/id_ed25519_github_habit"
RETENTION_DAYS=30
DATE=$(date "+%Y%m%d_%H%M%S")

log() {
    local msg="[$(date "+%Y-%m-%d %H:%M:%S")] $*"
    echo "$msg"
    if [[ -w "$LOG_FILE" ]] || [[ ! -e "$LOG_FILE" && -w "$(dirname "$LOG_FILE")" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
}

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

log "=== 开始执行好习惯数据库自动备份流水线 ==="

# 1. 触发 SQLite WAL 检查点刷盘，确保所有内存与临时 WAL 数据全部落盘
if [[ -f "$APP_DIR/habit.db" ]]; then
    sudo -u www-data sqlite3 "$APP_DIR/habit.db" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
    log "1. SQLite WAL 检查点刷盘已完成。"
else
    log "错误: 未找到数据库文件 $APP_DIR/habit.db"
    exit 1
fi

# 2. 通过 SQLite 在线备份 API 热备份数据库（安全无锁，防止损坏）
TEMP_DB="$BACKUP_DIR/habit_${DATE}.db"
TEMP_JSON="$BACKUP_DIR/data_${DATE}.json"
ARCHIVE_FILE="$BACKUP_DIR/habit_backup_${DATE}.tar.gz"

sudo -u www-data sqlite3 "$APP_DIR/habit.db" ".backup '$TEMP_DB'"
if [[ -f "$APP_DIR/data.json" ]]; then
    sudo -u www-data cp -f "$APP_DIR/data.json" "$TEMP_JSON"
fi

# 3. 打包压缩归档
FILES_TO_PACK=("habit_${DATE}.db")
if [[ -f "$TEMP_JSON" ]]; then
    FILES_TO_PACK+=("data_${DATE}.json")
fi

tar -czf "$ARCHIVE_FILE" -C "$BACKUP_DIR" "${FILES_TO_PACK[@]}"
rm -f "$TEMP_DB" "$TEMP_JSON"

# 4. 校验压缩包完整性
if tar -tzf "$ARCHIVE_FILE" >/dev/null 2>&1; then
    ARCHIVE_SIZE=$(du -h "$ARCHIVE_FILE" | cut -f1)
    log "2. 本地快照已成功创建: $(basename "$ARCHIVE_FILE") (体积: $ARCHIVE_SIZE)"
else
    log "错误: 归档文件损坏或创建失败: $ARCHIVE_FILE"
    exit 1
fi

# 5. 清理历史旧备份（保留最近 30 天）
DELETED_COUNT=$(find "$BACKUP_DIR" -type f -name "habit_backup_*.tar.gz" -mtime +"$RETENTION_DAYS" -print -delete 2>/dev/null | wc -l)
if [[ "$DELETED_COUNT" -gt 0 ]]; then
    log "3. 已自动清理超过 ${RETENTION_DAYS} 天的历史备份文件共 ${DELETED_COUNT} 个。"
else
    log "3. 历史备份保留策略校验完毕 (保留最近 ${RETENTION_DAYS} 天)。"
fi

# 6. 维护文件所有权归属 www-data
chown -R www-data:www-data "$BACKUP_DIR" 2>/dev/null || true
chown www-data:www-data "$LOG_FILE" 2>/dev/null || true

# 7. 可选增量同步至 GitHub (如果 Deploy Key 已经授权)
if [[ -f "$SSH_KEY" ]]; then
    AUTH_CHECK=$(ssh -i "$SSH_KEY" -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 || true)
    if echo "$AUTH_CHECK" | grep -qi "successfully authenticated"; then
        log "4. 检测到 GitHub 访问密钥有效，同步最新数据至 GitHub..."
        cd "$APP_DIR"
        export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        git add habit.db data.json
        if git status --porcelain habit.db data.json | grep -q .; then
            git commit -m "backup(data): auto backup habit.db & data.json [$(date "+%Y-%m-%d %H:%M:%S")]" >> "$LOG_FILE" 2>&1
            git push origin main >> "$LOG_FILE" 2>&1
            log "   GitHub 远程同步已完成并成功推送到 main 分支！"
        else
            log "   数据无新变动，跳过 Git 提交与推送。"
        fi
    else
        log "4. GitHub 访问密钥未授权或无法连接，跳过远程推送（本地 30 天定时归档运行正常）。"
    fi
fi

# 保证整个工作目录归属 www-data
chown -R www-data:www-data "$APP_DIR" 2>/dev/null || true
log "=== 数据库自动备份流水线执行完毕 ==="
