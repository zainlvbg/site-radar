"""
数据库模块 - SQLite 存储
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from src import DB_PATH, SCREENSHOTS_DIR

logger = logging.getLogger("site-radar.db")


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PageResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ErrorType(str, Enum):
    CONSOLE = "console"
    EXCEPTION = "exception"
    NETWORK = "network"


@dataclass
class Run:
    """巡检运行记录"""
    id: Optional[int] = None
    run_uuid: str = ""
    trigger_type: str = "manual"  # scheduled / manual
    status: str = RunStatus.RUNNING
    total_pages: int = 0
    completed_pages: int = 0
    failed_pages: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class PageResult:
    """页面巡检结果"""
    id: Optional[int] = None
    run_id: int = 0
    page_id: int = 0
    url: str = ""
    status: str = PageResultStatus.SUCCESS
    http_status: Optional[int] = None
    load_time: Optional[int] = None  # ms
    dom_content_loaded: Optional[int] = None  # ms
    screenshot_path: Optional[str] = None
    error_count: int = 0
    warning_count: int = 0
    request_error_count: int = 0
    
    # Lighthouse 得分
    lh_performance_score: Optional[int] = None
    lh_accessibility_score: Optional[int] = None
    lh_best_practices_score: Optional[int] = None
    lh_seo_score: Optional[int] = None
    
    # Web Vitals
    lh_lcp: Optional[int] = None  # ms
    lh_fcp: Optional[int] = None  # ms
    lh_cls: Optional[float] = None
    lh_tbt: Optional[int] = None  # ms
    lh_si: Optional[int] = None  # ms
    
    # 原始数据
    raw_lighthouse: Optional[str] = None
    
    # 时间
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration: Optional[int] = None  # ms
    
    # 错误信息
    error_message: Optional[str] = None


@dataclass
class ErrorRecord:
    """错误记录"""
    id: Optional[int] = None
    page_result_id: int = 0
    run_id: int = 0
    page_id: int = 0
    error_type: str = ErrorType.CONSOLE
    level: str = "error"  # error / warning / info
    message: str = ""
    source: Optional[str] = None
    line_number: Optional[int] = None
    column_number: Optional[int] = None
    url: Optional[str] = None
    http_status: Optional[int] = None
    stack_trace: Optional[str] = None
    occurred_at: Optional[str] = None


class Database:
    """SQLite 数据库操作"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # runs 表：每次巡检运行
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_uuid TEXT NOT NULL UNIQUE,
                    trigger_type TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL DEFAULT 'running',
                    total_pages INTEGER NOT NULL DEFAULT 0,
                    completed_pages INTEGER NOT NULL DEFAULT 0,
                    failed_pages INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT,
                    error_message TEXT
                )
            ''')
            
            # page_results 表：页面巡检结果
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS page_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    page_id INTEGER NOT NULL DEFAULT 0,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'success',
                    http_status INTEGER,
                    load_time INTEGER,
                    dom_content_loaded INTEGER,
                    screenshot_path TEXT,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    request_error_count INTEGER NOT NULL DEFAULT 0,
                    
                    lh_performance_score INTEGER,
                    lh_accessibility_score INTEGER,
                    lh_best_practices_score INTEGER,
                    lh_seo_score INTEGER,
                    
                    lh_lcp INTEGER,
                    lh_fcp INTEGER,
                    lh_cls REAL,
                    lh_tbt INTEGER,
                    lh_si INTEGER,
                    
                    raw_lighthouse TEXT,
                    
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT,
                    duration INTEGER,
                    error_message TEXT,
                    
                    FOREIGN KEY (run_id) REFERENCES runs(id)
                )
            ''')
            
            # 为已有数据库添加 error_message 列
            try:
                cursor.execute('ALTER TABLE page_results ADD COLUMN error_message TEXT')
            except:
                pass
            
            # errors 表：错误记录
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_result_id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    page_id INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'error',
                    message TEXT NOT NULL,
                    source TEXT,
                    line_number INTEGER,
                    column_number INTEGER,
                    url TEXT,
                    http_status INTEGER,
                    stack_trace TEXT,
                    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
                    
                    FOREIGN KEY (page_result_id) REFERENCES page_results(id),
                    FOREIGN KEY (run_id) REFERENCES runs(id)
                )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_page_results_run_id ON page_results(run_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_page_results_url ON page_results(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_errors_run_id ON errors(run_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_errors_page_result_id ON errors(page_result_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_errors_occurred_at ON errors(occurred_at)')
            
            conn.commit()
            logger.info(f"✅ 数据库初始化完成: {self.db_path}")
    
    # ========== Runs 表操作 ==========
    
    def create_run(self, run: Run) -> int:
        """创建新的巡检运行"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO runs (run_uuid, trigger_type, status, total_pages, started_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                run.run_uuid,
                run.trigger_type,
                run.status,
                run.total_pages,
                run.started_at or datetime.utcnow().isoformat()
            ))
            conn.commit()
            run_id = cursor.lastrowid
            logger.info(f"📋 创建新运行: #{run_id} (uuid: {run.run_uuid[:8]}...)")
            return run_id
    
    def update_run(self, run: Run):
        """更新运行状态"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE runs 
                SET status=?, completed_pages=?, failed_pages=?, completed_at=?, error_message=?
                WHERE id=?
            ''', (
                run.status,
                run.completed_pages,
                run.failed_pages,
                run.completed_at,
                run.error_message,
                run.id
            ))
            conn.commit()
    
    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """获取运行详情"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM runs WHERE id = ?', (run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_latest_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的运行记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM runs 
                ORDER BY started_at DESC 
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ========== Page Results 表操作 ==========
    
    def create_page_result(self, result: PageResult) -> int:
        """创建页面结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO page_results (
                    run_id, page_id, url, status, http_status, load_time, 
                    dom_content_loaded, screenshot_path, error_count, warning_count, 
                    request_error_count, lh_performance_score, lh_accessibility_score,
                    lh_best_practices_score, lh_seo_score, lh_lcp, lh_fcp, lh_cls,
                    lh_tbt, lh_si, raw_lighthouse, started_at, completed_at, duration, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                result.run_id, result.page_id, result.url, result.status,
                result.http_status, result.load_time, result.dom_content_loaded,
                result.screenshot_path, result.error_count, result.warning_count,
                result.request_error_count, result.lh_performance_score,
                result.lh_accessibility_score, result.lh_best_practices_score,
                result.lh_seo_score, result.lh_lcp, result.lh_fcp, result.lh_cls,
                result.lh_tbt, result.lh_si, result.raw_lighthouse,
                result.started_at, result.completed_at, result.duration,
                result.error_message
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_page_results(self, run_id: int) -> List[Dict[str, Any]]:
        """获取运行的所有页面结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM page_results WHERE run_id = ?
            ''', (run_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_page_history(self, url: str, limit: int = 30) -> List[Dict[str, Any]]:
        """获取页面的历史巡检结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT pr.*, r.started_at as run_started_at
                FROM page_results pr
                JOIN runs r ON pr.run_id = r.id
                WHERE pr.url = ? AND r.status = 'completed'
                ORDER BY r.started_at DESC
                LIMIT ?
            ''', (url, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_urls_with_history(self) -> List[str]:
        """获取所有有历史记录的 URL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT url FROM page_results ORDER BY url
            ''')
            return [row[0] for row in cursor.fetchall()]
    
    # ========== Errors 表操作 ==========
    
    def create_error(self, error: ErrorRecord) -> int:
        """记录错误"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO errors (
                    page_result_id, run_id, page_id, error_type, level,
                    message, source, line_number, column_number, url,
                    http_status, stack_trace, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                error.page_result_id, error.run_id, error.page_id,
                error.error_type, error.level, error.message,
                error.source, error.line_number, error.column_number,
                error.url, error.http_status, error.stack_trace,
                error.occurred_at or datetime.utcnow().isoformat()
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_run_errors(self, run_id: int) -> List[Dict[str, Any]]:
        """获取运行的所有错误"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM errors WHERE run_id = ? ORDER BY occurred_at
            ''', (run_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_errors(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近的错误"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM errors 
                WHERE occurred_at >= datetime('now', '-' || ? || ' hours')
                ORDER BY occurred_at DESC
            ''', (hours,))
            return [dict(row) for row in cursor.fetchall()]
    
    def is_new_error(self, message: str, error_type: str, hours: int = 24) -> bool:
        """检查是否是新错误（在指定时间内没有出现过）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM errors 
                WHERE message = ? AND error_type = ? 
                AND occurred_at >= datetime('now', '-' || ? || ' hours')
            ''', (message, error_type, hours))
            count = cursor.fetchone()[0]
            return count == 0


# 全局数据库实例
db = Database()
