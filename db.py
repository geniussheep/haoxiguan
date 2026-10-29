#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杨妙绮好习惯魔法存折 - SQLite 数据库管理模块
提供高效轻量的 ACID 存储、自动迁移、连接池与线程安全
"""

import json
import os
import sqlite3
import threading
from datetime import datetime

class HabitDB:
    def __init__(self, db_path, json_fallback_path=None):
        self.db_path = os.path.abspath(db_path)
        self.json_fallback_path = os.path.abspath(json_fallback_path) if json_fallback_path else None
        self._lock = threading.Lock()
        self._local = threading.local()
        self.init_schema()
        self.auto_migrate_from_json()

    def _get_conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def init_schema(self):
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS habit_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                score INTEGER NOT NULL DEFAULT 0,
                princess_id TEXT NOT NULL DEFAULT 'belle',
                sound_enabled INTEGER NOT NULL DEFAULT 1,
                week_writing_count INTEGER NOT NULL DEFAULT 0,
                week_jump_count INTEGER NOT NULL DEFAULT 0,
                has_claimed_weekly_writing INTEGER NOT NULL DEFAULT 0,
                has_claimed_weekly_jump INTEGER NOT NULL DEFAULT 0,
                today_earned INTEGER NOT NULL DEFAULT 0,
                last_check_date TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS habit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pts INTEGER NOT NULL,
                reason TEXT NOT NULL,
                display_time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_revoked INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_history_order ON habit_history(id DESC);
            CREATE INDEX IF NOT EXISTS idx_history_revoked ON habit_history(is_revoked);

            CREATE TABLE IF NOT EXISTS habit_prizes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cost INTEGER NOT NULL,
                description TEXT,
                icon TEXT,
                is_grand INTEGER NOT NULL DEFAULT 0,
                is_builtin INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                status INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS habit_custom_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                default_pts INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            """)
            conn.commit()

    def auto_migrate_from_json(self):
        """如果 SQLite 为空且存在 JSON 文件，自动无损导入历史数据"""
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT count(*) as c FROM habit_profile WHERE id=1")
            has_profile = cur.fetchone()["c"] > 0
            if has_profile:
                return

            candidates = []
            if self.json_fallback_path and os.path.exists(self.json_fallback_path):
                candidates.append(self.json_fallback_path)
            
            # 常见候选路径
            base_dir = os.path.dirname(self.db_path)
            candidates.extend([
                os.path.join(base_dir, "data(1).json"),
                os.path.join(base_dir, "data.json")
            ])

            chosen_file = None
            for f in candidates:
                if os.path.exists(f):
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                            if data.get("score", 0) > 0 or len(data.get("history", [])) > 0:
                                chosen_file = f
                                break
                    except Exception:
                        pass

            if not chosen_file and os.path.exists(candidates[-1]):
                chosen_file = candidates[-1]

            if not chosen_file:
                # 初始空档案
                cur.execute("INSERT OR IGNORE INTO habit_profile (id, score, princess_id) VALUES (1, 0, 'belle')")
                conn.commit()
                return

            print(f"[SQLite] 正在从 {chosen_file} 迁移初始数据到 SQLite...")
            try:
                with open(chosen_file, "r", encoding="utf-8") as fp:
                    d = json.load(fp)

                cur.execute("""
                INSERT OR REPLACE INTO habit_profile (
                    id, score, princess_id, sound_enabled, week_writing_count, week_jump_count,
                    has_claimed_weekly_writing, has_claimed_weekly_jump, today_earned, last_check_date
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    d.get("score", 0),
                    d.get("princessId", "belle"),
                    1 if d.get("soundEnabled", True) else 0,
                    d.get("weekWritingCount", 0),
                    d.get("weekJumpCount", 0),
                    1 if d.get("hasClaimedWeeklyWriting", False) else 0,
                    1 if d.get("hasClaimedWeeklyJump", False) else 0,
                    d.get("todayEarned", 0),
                    d.get("lastCheckDate", "")
                ))

                for item in reversed(d.get("history", [])):
                    cur.execute("""
                    INSERT INTO habit_history (pts, reason, display_time)
                    VALUES (?, ?, ?)
                    """, (item.get("pts", 0), item.get("reason", ""), item.get("time", "")))

                for idx, p in enumerate(d.get("prizes", [])):
                    cur.execute("""
                    INSERT OR REPLACE INTO habit_prizes (id, name, cost, description, icon, is_grand, is_builtin, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        p.get("id"), p.get("name"), p.get("cost", 0), p.get("desc", ""),
                        p.get("icon", ""), 1 if p.get("isGrand") else 0,
                        1 if p.get("isBuiltin") else 0, idx
                    ))

                for idx, r in enumerate(d.get("customReasons", [])):
                    cur.execute("INSERT INTO habit_custom_rules (category, title, sort_order) VALUES (?, ?, ?)", ("earn", r, idx))

                for idx, r in enumerate(d.get("customDeductReasons", [])):
                    cur.execute("INSERT INTO habit_custom_rules (category, title, sort_order) VALUES (?, ?, ?)", ("deduct", r, idx))

                conn.commit()
                print(f"[SQLite] 迁移成功！当前总积分: {d.get('score')}, 明细条数: {len(d.get('history', []))}")
            except Exception as e:
                print(f"[SQLite] 迁移 JSON 失败: {e}")

    def get_state(self):
        """组装符合前端全量规范的 state 字典"""
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()

            cur.execute("SELECT * FROM habit_profile WHERE id=1")
            prof_row = cur.fetchone()
            if not prof_row:
                return {}

            prof = dict(prof_row)

            # 读取历史明细 (未撤销项，最新在最前)
            cur.execute("SELECT pts, reason, display_time as time FROM habit_history WHERE is_revoked = 0 ORDER BY id DESC")
            history = [dict(r) for r in cur.fetchall()]

            # 读取奖品商城
            cur.execute("SELECT id, name, cost, description as desc, icon, is_grand as isGrand, is_builtin as isBuiltin FROM habit_prizes WHERE status = 1 ORDER BY sort_order ASC")
            prizes = []
            for r in cur.fetchall():
                p = dict(r)
                p["isGrand"] = bool(p["isGrand"])
                p["isBuiltin"] = bool(p["isBuiltin"])
                prizes.append(p)

            # 读取自定义加减分项
            cur.execute("SELECT title FROM habit_custom_rules WHERE category='earn' ORDER BY sort_order ASC, id ASC")
            custom_reasons = [r["title"] for r in cur.fetchall()]

            cur.execute("SELECT title FROM habit_custom_rules WHERE category='deduct' ORDER BY sort_order ASC, id ASC")
            custom_deduct_reasons = [r["title"] for r in cur.fetchall()]

            return {
                "score": prof["score"],
                "princessId": prof["princess_id"],
                "soundEnabled": bool(prof["sound_enabled"]),
                "history": history,
                "weekWritingCount": prof["week_writing_count"],
                "weekJumpCount": prof["week_jump_count"],
                "hasClaimedWeeklyWriting": bool(prof["has_claimed_weekly_writing"]),
                "hasClaimedWeeklyJump": bool(prof["has_claimed_weekly_jump"]),
                "todayEarned": prof["today_earned"],
                "lastCheckDate": prof["last_check_date"],
                "customReasons": custom_reasons,
                "customDeductReasons": custom_deduct_reasons,
                "prizes": prizes
            }

    def save_state(self, state):
        """保存全量 state 字典到 SQLite"""
        if not isinstance(state, dict):
            return False

        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()

            try:
                # 1. 更新全局 profile
                cur.execute("""
                INSERT OR REPLACE INTO habit_profile (
                    id, score, princess_id, sound_enabled, week_writing_count, week_jump_count,
                    has_claimed_weekly_writing, has_claimed_weekly_jump, today_earned, last_check_date, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    state.get("score", 0),
                    state.get("princessId", "belle"),
                    1 if state.get("soundEnabled", True) else 0,
                    state.get("weekWritingCount", 0),
                    state.get("weekJumpCount", 0),
                    1 if state.get("hasClaimedWeeklyWriting", False) else 0,
                    1 if state.get("hasClaimedWeeklyJump", False) else 0,
                    state.get("todayEarned", 0),
                    state.get("lastCheckDate", "")
                ))

                # 2. 如果包含 history 数组，同步更新历史表
                if "history" in state and isinstance(state["history"], list):
                    cur.execute("DELETE FROM habit_history")
                    for item in reversed(state["history"]):
                        cur.execute("""
                        INSERT INTO habit_history (pts, reason, display_time)
                        VALUES (?, ?, ?)
                        """, (item.get("pts", 0), item.get("reason", ""), item.get("time", "")))

                # 3. 如果包含 prizes，同步更新奖品
                if "prizes" in state and isinstance(state["prizes"], list):
                    cur.execute("DELETE FROM habit_prizes")
                    for idx, p in enumerate(state["prizes"]):
                        cur.execute("""
                        INSERT OR REPLACE INTO habit_prizes (id, name, cost, description, icon, is_grand, is_builtin, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            p.get("id"), p.get("name"), p.get("cost", 0), p.get("desc", ""),
                            p.get("icon", ""), 1 if p.get("isGrand") else 0,
                            1 if p.get("isBuiltin") else 0, idx
                        ))

                # 4. 如果包含自定义理由
                if "customReasons" in state and isinstance(state["customReasons"], list):
                    cur.execute("DELETE FROM habit_custom_rules WHERE category='earn'")
                    for idx, r in enumerate(state["customReasons"]):
                        cur.execute("INSERT INTO habit_custom_rules (category, title, sort_order) VALUES ('earn', ?, ?)", (r, idx))

                if "customDeductReasons" in state and isinstance(state["customDeductReasons"], list):
                    cur.execute("DELETE FROM habit_custom_rules WHERE category='deduct'")
                    for idx, r in enumerate(state["customDeductReasons"]):
                        cur.execute("INSERT INTO habit_custom_rules (category, title, sort_order) VALUES ('deduct', ?, ?)", (r, idx))

                conn.commit()

                # 异步或同步写备份 JSON
                if self.json_fallback_path:
                    try:
                        with open(self.json_fallback_path, "w", encoding="utf-8") as fp:
                            json.dump(state, fp, ensure_ascii=False, indent=2)
                    except Exception as e:
                        print(f"[SQLite] 备份写入 JSON 警告: {e}")

                return True
            except Exception as e:
                conn.rollback()
                print(f"[SQLite] 保存失败: {e}")
                return False
