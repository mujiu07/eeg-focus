"""
专注小蛙 · 本地数据存储
=========================
v1.8.1 的 SQLite 主存储与应用数据目录管理。

设计边界：
  * 数据库位于用户文档目录下的 ``专注小蛙/profiles.db``（可用环境变量
    ``FOCUS_FROG_DATA_DIR`` 覆盖，便于测试与未来桌面封装）。
  * settings.json 只保存应用级设置，不保存昵称、校准值或脑电。
  * 本模块不依赖 Flask/FastAPI，可使用 Python 标准库 sqlite3 单独测试。
  * SQLite 本身没有静态加密；这一点在 API 状态和报告里明确标注。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .calibration import (
    PROTOCOL_VERSION, daily_status, device_key as calibration_device_key, local_date,
)
from . import difficulty

APP_NAME = "专注小蛙"
SCHEMA_VERSION = 4
MAX_PROFILES = 12
AVATARS = ("frog", "tadpole", "lotus", "fish", "dragonfly", "snail")
AVATAR_LABELS = {
    "frog": "小蛙",
    "tadpole": "小蝌蚪",
    "lotus": "荷花",
    "fish": "小鱼",
    "dragonfly": "蜻蜓",
    "snail": "蜗牛",
}
PROFILE_KEYS = (
    "bf-wallet", "bf-achievements", "bf-owned", "bf-owned-at", "bf-outfit",
    "bf-checkin", "bf-heart", "bf-heart-rest", "bf-heart-weight",
    "bf-duration-sec", "bf-calib", "bf-tutorial-done", "bf-dev-tutorial-done",
    "bf-sky", "bf-music-on", "bf-music-index", "bf-music-state", "bf-music-vol",
)


class StorageError(RuntimeError):
    """可读的存储/路径/权限错误，API 层转成 4xx/5xx。"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: Any, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _platform_documents() -> Path:
    """返回当前平台用户的真实文档目录。

    Windows 上优先调用 Shell API，能跟随 OneDrive 的“文档”重定向；
    macOS/Linux 使用 ~/Documents。任何检查失败都回退到用户主目录下的
    Documents，而不是硬编码用户名。
    """
    home = Path.home()
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5, SHGFP_TYPE_CURRENT = 0
            got = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if got == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return home / "Documents"


def platform_config_dir() -> Path:
    """应用级指针目录：只保存“数据目录在哪里”，不含个人资料。"""
    home = Path.home()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (home / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config")) / APP_NAME


def default_data_dir() -> Path:
    override = os.environ.get("FOCUS_FROG_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _platform_documents() / APP_NAME


def cloud_sync_hint(path: Path) -> Optional[str]:
    text = str(path).lower().replace("\\", "/")
    if "onedrive" in text:
        return "当前路径位于 OneDrive，可能被云同步。建议选择不同步的本地目录。"
    if "icloud" in text or "mobile documents" in text:
        return "当前路径位于 iCloud Drive，可能被云同步。建议选择不同步的本地目录。"
    if "dropbox" in text or "google drive" in text or "googledrive" in text:
        return "当前路径位于第三方同步目录，可能被云同步。建议选择不同步的本地目录。"
    if "坚果云" in str(path) or "nutstore" in text:
        return "当前路径位于坚果云同步目录，可能被云同步。建议选择不同步的本地目录。"
    return None


def _check_writable(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".write-test-", dir=str(path), delete=True):
            pass
    except OSError as exc:
        raise StorageError(f"数据目录不可写：{path}（{exc}）") from exc


def _safe_absolute_dir(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise StorageError("数据目录不能为空")
    candidate = Path(str(raw).strip()).expanduser()
    if not candidate.is_absolute():
        raise StorageError("请填写绝对路径，例如 /Users/name/Documents/专注小蛙")
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise StorageError(f"路径无法解析：{candidate}（{exc}）") from exc
    if resolved == Path(resolved.anchor):
        raise StorageError("不能把数据目录设置为磁盘根目录")
    if resolved.exists() and not resolved.is_dir():
        raise StorageError("目标路径不是文件夹")
    return resolved


class StorageManager:
    """数据库、目录、备份与用户数据访问的统一入口。"""

    def __init__(self, data_dir: Optional[Path | str] = None):
        self.lock = threading.RLock()
        self.error: Optional[str] = None
        self.default_dir = default_data_dir()
        self.config_dir = platform_config_dir()
        self.pointer_path = self.config_dir / "location.json"
        env_override = os.environ.get("FOCUS_FROG_DATA_DIR")
        if data_dir is not None:
            chosen = Path(data_dir).expanduser()
        elif env_override:
            # 自动化测试/便携启动显式指定时优先于用户指针，避免测试碰真实档案。
            chosen = Path(env_override).expanduser()
        else:
            chosen = self._read_pointer()
        if chosen is None:
            chosen = self.default_dir
        self.root = Path(chosen).expanduser()
        self.settings_path = self.root / "settings.json"
        self.db_path = self.root / "profiles.db"
        self.reports_dir = self.root / "reports"
        self.recordings_dir = self.root / "recordings"
        self.backups_dir = self.root / "backups"
        try:
            self._ensure_layout()
            self._migrate()
            self._cleanup_empty_legacy()
        except StorageError as exc:
            self.error = str(exc)

    # ------------------------------------------------------------------
    # 目录/设置
    # ------------------------------------------------------------------
    def _read_pointer(self) -> Optional[Path]:
        try:
            raw = json.loads(self.pointer_path.read_text(encoding="utf-8"))
            value = raw.get("data_dir")
            if value:
                return Path(value).expanduser()
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _write_pointer(self, root: Path) -> None:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            _check_writable(self.config_dir)
            tmp = self.pointer_path.with_suffix(".tmp")
            tmp.write_text(_json({"data_dir": str(root), "updated_at": _now()}) + "\n", encoding="utf-8")
            os.replace(tmp, self.pointer_path)
        except OSError as exc:
            raise StorageError(f"无法保存数据目录指针：{exc}") from exc

    def _ensure_layout(self) -> None:
        _check_writable(self.root)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        for folder in (self.reports_dir, self.recordings_dir, self.backups_dir):
            _check_writable(folder)
            try:
                os.chmod(folder, 0o700)
            except OSError:
                pass
        if not self.settings_path.exists():
            payload = {
                "app": APP_NAME,
                "schema": SCHEMA_VERSION,
                "created_at": _now(),
                "note": "应用级设置；昵称、校准、游戏记录与脑电不写在这里",
            }
            self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                os.chmod(self.settings_path, 0o600)
            except OSError:
                pass
        # 确保用户能从系统目录找到应用；已有其他指针时保留它，不悄悄迁移。
        if not self.pointer_path.exists():
            self._write_pointer(self.root)

    @contextmanager
    def _db(self):
        if self.error:
            raise StorageError(self.error)
        conn = sqlite3.connect(str(self.db_path), timeout=12)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._db() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL,
                    avatar TEXT NOT NULL DEFAULT 'frog',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    is_system INTEGER NOT NULL DEFAULT 0,
                    wallet_balance INTEGER NOT NULL DEFAULT 0,
                    wallet_meta TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS calibrations (
                    calibration_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'daily',
                    baseline REAL NOT NULL,
                    q10 REAL, q50 REAL, q90 REAL,
                    range_low REAL, range_high REAL,
                    calibrated_at TEXT NOT NULL,
                    calibrated_at_ms INTEGER NOT NULL,
                    calibration_date TEXT,
                    timezone_offset_min INTEGER,
                    device_key TEXT,
                    method TEXT,
                    source_name TEXT,
                    source_info TEXT NOT NULL DEFAULT '{}',
                    n_frames INTEGER NOT NULL DEFAULT 0,
                    signal_quality TEXT NOT NULL DEFAULT '{}',
                    protocol_version TEXT NOT NULL DEFAULT 'legacy',
                    mapping_version TEXT NOT NULL DEFAULT 'legacy',
                    stages_json TEXT NOT NULL DEFAULT '{}',
                    effective_sec REAL NOT NULL DEFAULT 0,
                    elapsed_sec REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'legacy',
                    reference_baseline_id TEXT,
                    algorithm_version TEXT NOT NULL DEFAULT 'unknown',
                    params_version TEXT NOT NULL DEFAULT 'v1.8.2',
                    is_valid INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS reference_baselines (
                    baseline_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    baseline REAL NOT NULL,
                    range_low REAL, range_high REAL,
                    valid_from TEXT,
                    valid_until TEXT,
                    source_info TEXT NOT NULL DEFAULT '{}',
                    algorithm_version TEXT NOT NULL DEFAULT 'unknown',
                    version TEXT NOT NULL DEFAULT 'v1',
                    q15 REAL, q85 REAL, n_frames INTEGER NOT NULL DEFAULT 0,
                    protocol_version TEXT NOT NULL DEFAULT 'legacy',
                    mapping_version TEXT NOT NULL DEFAULT 'legacy',
                    device_key TEXT,
                    stages_json TEXT NOT NULL DEFAULT '{}',
                    is_initial INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active',
                    superseded_by TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                    started_at TEXT,
                    ended_at TEXT,
                    duration_sec REAL,
                    played_sec REAL,
                    calibration_id TEXT,
                    reference_baseline_id TEXT,
                    calibration_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    reference_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    algorithm_version TEXT NOT NULL DEFAULT 'unknown',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    source_json TEXT NOT NULL DEFAULT '{}',
                    demo INTEGER NOT NULL DEFAULT 0,
                    total_score INTEGER,
                    wallet_points INTEGER NOT NULL DEFAULT 0,
                    jumps INTEGER,
                    successful_jumps INTEGER,
                    missed_jumps INTEGER,
                    eeg_base_score REAL,
                    actual_score REAL,
                    valid_signal_ratio REAL,
                    difficulty_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    purpose TEXT NOT NULL DEFAULT 'game',
                    assessment_id TEXT,
                    report_json TEXT NOT NULL DEFAULT '{}',
                    finished INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                    round_no INTEGER,
                    charge_sec REAL,
                    reaction_sec REAL,
                    potential INTEGER,
                    awarded INTEGER,
                    success INTEGER,
                    multiplier REAL,
                    mean_score REAL,
                    above_ratio REAL,
                    early_taps INTEGER,
                    cooldown_count INTEGER,
                    cooldown_sec REAL,
                    eval_sec REAL,
                    charge_active_sec REAL,
                    below_threshold_sec REAL,
                    stale_sec REAL,
                    decay_events INTEGER,
                    decay_sec REAL,
                    energy_gain REAL,
                    energy_loss REAL,
                    bullet_sec REAL,
                    jump_anim_sec REAL,
                    paused_sec REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(session_id, round_no)
                );
                CREATE TABLE IF NOT EXISTS assessments (
                    assessment_id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT UNIQUE,
                    protocol_version TEXT NOT NULL DEFAULT 'standard_v1',
                    planned_sec REAL NOT NULL DEFAULT 90,
                    fixed_factor REAL NOT NULL DEFAULT 1.0,
                    seed TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    simulation INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    ended_at TEXT,
                    calibration_id TEXT,
                    reference_baseline_id TEXT,
                    device_json TEXT NOT NULL DEFAULT '{}',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    features_json TEXT NOT NULL DEFAULT '{}',
                    behavior_json TEXT NOT NULL DEFAULT '{}',
                    report_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS difficulty_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    reason TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS difficulty_profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    factor REAL NOT NULL DEFAULT 1.0,
                    auto_enabled INTEGER NOT NULL DEFAULT 1,
                    manual_lock INTEGER NOT NULL DEFAULT 0,
                    streak_hard INTEGER NOT NULL DEFAULT 0,
                    streak_easy INTEGER NOT NULL DEFAULT 0,
                    last_decision TEXT,
                    last_reason TEXT,
                    last_metrics_json TEXT NOT NULL DEFAULT '{}',
                    last_session_id TEXT,
                    last_calibration_id TEXT,
                    last_device_key TEXT,
                    last_adjusted_at TEXT,
                    strategy_version TEXT NOT NULL DEFAULT 'adaptive_v1',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inventories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'shop',
                    acquired_at TEXT NOT NULL,
                    equipped INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(user_id, item_id, kind)
                );
                CREATE TABLE IF NOT EXISTS achievements (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    achievement_id TEXT NOT NULL,
                    unlocked_at TEXT,
                    seen INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, achievement_id)
                );
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    amount INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    session_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    balance_after INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    setting_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, setting_key)
                );
                CREATE TABLE IF NOT EXISTS recordings (
                    recording_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT,
                    path TEXT NOT NULL,
                    consent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    import_key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}',
                    imported_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_calibrations_user ON calibrations(user_id, calibrated_at_ms);
                CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_transactions(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
                CREATE INDEX IF NOT EXISTS idx_assessments_user ON assessments(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_assessments_session ON assessments(session_id);
            """)
            # v1.8.2：在 v1.8.1 数据库上原地补列；不重建表，不触碰用户/积分/历史数据。
            self._ensure_columns(conn, "calibrations", {
                "calibration_date": "TEXT", "timezone_offset_min": "INTEGER",
                "device_key": "TEXT", "protocol_version": "TEXT NOT NULL DEFAULT 'legacy'",
                "mapping_version": "TEXT NOT NULL DEFAULT 'legacy'",
                "stages_json": "TEXT NOT NULL DEFAULT '{}'", "effective_sec": "REAL NOT NULL DEFAULT 0",
                "elapsed_sec": "REAL NOT NULL DEFAULT 0", "status": "TEXT NOT NULL DEFAULT 'legacy'",
                "reference_baseline_id": "TEXT",
            })
            self._ensure_columns(conn, "reference_baselines", {
                "version": "TEXT NOT NULL DEFAULT 'v1'", "q15": "REAL", "q85": "REAL",
                "n_frames": "INTEGER NOT NULL DEFAULT 0",
                "protocol_version": "TEXT NOT NULL DEFAULT 'legacy'",
                "mapping_version": "TEXT NOT NULL DEFAULT 'legacy'", "device_key": "TEXT",
                "stages_json": "TEXT NOT NULL DEFAULT '{}'",
                "is_initial": "INTEGER NOT NULL DEFAULT 1", "status": "TEXT NOT NULL DEFAULT 'active'",
                "superseded_by": "TEXT",
            })
            self._ensure_columns(conn, "sessions", {
                "reference_baseline_id": "TEXT",
                "calibration_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "reference_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "purpose": "TEXT NOT NULL DEFAULT 'game'",
                "assessment_id": "TEXT",
            })
            self._ensure_columns(conn, "rounds", {
                "eval_sec": "REAL", "charge_active_sec": "REAL",
                "below_threshold_sec": "REAL", "stale_sec": "REAL",
                "decay_events": "INTEGER", "decay_sec": "REAL",
                "energy_gain": "REAL", "energy_loss": "REAL",
                "bullet_sec": "REAL", "jump_anim_sec": "REAL", "paused_sec": "REAL",
            })
            # v1.8.3：难度档案与可审计的局间调整记录。保留 v1.8.1 预留的
            # difficulty_history 表，只补列，不重建、不覆盖历史。
            self._ensure_columns(conn, "difficulty_history", {
                "before_factor": "REAL", "after_factor": "REAL",
                "direction": "TEXT", "decision": "TEXT",
                "metrics_json": "TEXT NOT NULL DEFAULT '{}'",
                "calibration_id": "TEXT", "strategy_version": "TEXT",
                "params_version": "TEXT", "source": "TEXT",
            })
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_difficulty_history_session "
                "ON difficulty_history(session_id) WHERE session_id IS NOT NULL AND session_id != ''"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_difficulty_history_user "
                "ON difficulty_history(user_id, created_at)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?, ?)",
                (SCHEMA_VERSION, _now()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(1, ?)",
                (_now(),),
            )

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # ------------------------------------------------------------------
    # 状态 / 路径 / 备份
    # ------------------------------------------------------------------
    def _cleanup_empty_legacy(self) -> None:
        """删除导入失败留下的空系统历史档案；有记录时保留。"""
        try:
            with self._db() as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE is_system = 1 AND status = 'archived' LIMIT 1"
                ).fetchone()
                if not row:
                    return
                uid = row["user_id"]
                sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (uid,)).fetchone()[0]
                imports = conn.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0]
                if sessions == 0 and imports == 0:
                    conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        except Exception:
            pass

    def status(self) -> dict:
        if self.error:
            return {"ok": False, "error": self.error, "data_dir": str(self.root),
                    "encrypted": False, "cloud_sync_hint": cloud_sync_hint(self.root)}
        try:
            usage = shutil.disk_usage(str(self.root))
            with self._db() as conn:
                counts = {
                    "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                    "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                    "calibrations": conn.execute("SELECT COUNT(*) FROM calibrations").fetchone()[0],
                    "rounds": conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0],
                    "assessments": conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0],
                    "backups": len(list(self.backups_dir.glob("*.db"))),
                }
                version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            return {
                "ok": True,
                "data_dir": str(self.root),
                "default_dir": str(self.default_dir),
                "database": str(self.db_path),
                "schema_version": version,
                "encrypted": False,
                "writable": True,
                "disk_free": usage.free,
                "disk_total": usage.total,
                "cloud_sync_hint": cloud_sync_hint(self.root),
                "counts": counts,
                "scope_note": "本地档案隔离，不是联网身份认证；SQLite 未做静态加密",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "data_dir": str(self.root),
                    "encrypted": False, "cloud_sync_hint": cloud_sync_hint(self.root)}

    def backups(self) -> list[dict]:
        out = []
        for path in sorted(self.backups_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = path.stat()
                out.append({"filename": path.name, "size": stat.st_size, "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")})
            except OSError:
                continue
        return out

    def backup(self, label: str = "manual") -> dict:
        safe = "".join(c for c in str(label or "manual") if c.isalnum() or c in "-_")[:40] or "manual"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"profiles-{stamp}-{safe}-{uuid.uuid4().hex[:5]}.db"
        dest = self.backups_dir / filename
        try:
            with self._db() as source:
                source.execute("PRAGMA wal_checkpoint(FULL)")
                target = sqlite3.connect(str(dest))
                try:
                    source.backup(target)
                finally:
                    target.close()
            check = sqlite3.connect(str(dest))
            try:
                result = check.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                check.close()
            if result != "ok":
                dest.unlink(missing_ok=True)
                raise StorageError(f"备份完整性检查失败：{result}")
            return {"ok": True, "filename": filename, "path": str(dest)}
        except StorageError:
            raise
        except Exception as exc:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"创建备份失败：{exc}") from exc

    def restore(self, filename: str, confirm: bool = False) -> dict:
        if not confirm:
            raise StorageError("恢复备份需要明确确认")
        name = Path(str(filename)).name
        if name != str(filename) or not name.endswith(".db"):
            raise StorageError("无效的备份文件名")
        source = self.backups_dir / name
        if not source.is_file():
            raise StorageError("备份文件不存在")
        check = sqlite3.connect(str(source))
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            has_schema = check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        finally:
            check.close()
        if result != "ok" or not has_schema:
            raise StorageError("备份文件损坏或不是有效数据库")
        pre = self.backup("before-restore")
        tmp = self.db_path.with_name(self.db_path.name + ".restore.tmp")
        try:
            shutil.copy2(source, tmp)
            # 在替换前再次验证临时副本
            v = sqlite3.connect(str(tmp))
            try:
                if v.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StorageError("恢复副本完整性检查失败")
            finally:
                v.close()
            for suffix in ("-wal", "-shm"):
                try:
                    Path(str(self.db_path) + suffix).unlink()
                except OSError:
                    pass
            os.replace(tmp, self.db_path)
            return {"ok": True, "restored": name, "pre_restore_backup": pre["filename"]}
        except StorageError:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise StorageError(f"恢复失败：{exc}") from exc

    def set_data_dir(self, raw: str, confirm: bool = False, migrate: bool = True) -> dict:
        if not confirm:
            raise StorageError("修改数据目录需要明确确认")
        target = _safe_absolute_dir(raw)
        if target == self.root:
            return {"ok": True, "data_dir": str(target), "migrated": False}
        root_resolved = self.root.resolve(strict=False)
        if target == root_resolved or root_resolved in target.parents or target in root_resolved.parents:
            raise StorageError("不能把数据目录切换到当前目录内部或其父目录，以避免递归迁移")
        forbidden = {"/System", "/Library", "/etc", "/usr", "/var", "/bin", "/sbin", "/opt"}
        if str(target) in forbidden or (os.name == "nt" and str(target).lower() in {"c:\\windows", "c:\\program files"}):
            raise StorageError("不能把数据目录设置为系统目录")
        if target.exists() and any(target.iterdir()):
            raise StorageError("目标目录非空；请选择一个空目录，避免覆盖已有数据")
        try:
            target.mkdir(parents=True, exist_ok=True)
            _check_writable(target)
        except OSError as exc:
            raise StorageError(f"目标目录不可写：{exc}") from exc
        if not migrate:
            self._write_pointer(target)
            self.root = target
            self.settings_path = target / "settings.json"
            self.db_path = target / "profiles.db"
            self.reports_dir = target / "reports"
            self.recordings_dir = target / "recordings"
            self.backups_dir = target / "backups"
            self._ensure_layout()
            self._migrate()
            return {"ok": True, "data_dir": str(target), "migrated": False}
        pre = self.backup("before-location-change")
        # 复制到一个临时兄弟目录，全部成功后再改指针，避免半复制状态。
        staging = target.parent / (target.name + ".migrating-" + uuid.uuid4().hex[:6])
        try:
            staging.mkdir(parents=True, exist_ok=False)
            for name in ("settings.json",):
                src = self.root / name
                if src.exists():
                    shutil.copy2(src, staging / name)
            if self.db_path.exists():
                with self._db() as source:
                    source.execute("PRAGMA wal_checkpoint(FULL)")
                    dst = sqlite3.connect(str(staging / "profiles.db"))
                    try:
                        source.backup(dst)
                    finally:
                        dst.close()
            for folder in (self.reports_dir, self.recordings_dir, self.backups_dir):
                if folder.exists():
                    shutil.copytree(folder, staging / folder.name, dirs_exist_ok=True)
            # staging 和 target 都是空目录：把 staging 内容移入 target
            for item in staging.iterdir():
                os.replace(item, target / item.name)
            staging.rmdir()
            check = sqlite3.connect(str(target / "profiles.db"))
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StorageError("迁移后的数据库完整性检查失败")
            finally:
                check.close()
            self._write_pointer(target)
            self.root = target
            self.settings_path = target / "settings.json"
            self.db_path = target / "profiles.db"
            self.reports_dir = target / "reports"
            self.recordings_dir = target / "recordings"
            self.backups_dir = target / "backups"
            self._migrate()
            return {"ok": True, "data_dir": str(target), "migrated": True,
                    "pre_change_backup": pre["filename"]}
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"迁移数据目录失败：{exc}") from exc

    def open_folder(self) -> dict:
        system = platform.system()
        if system == "Darwin":
            cmd = ["open", str(self.root)]
        elif os.name == "nt":
            cmd = ["explorer", str(self.root)]
        else:
            cmd = ["xdg-open", str(self.root)]
        try:
            proc = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=5)
            if proc.returncode != 0:
                raise StorageError("系统未能打开文件夹；请手动打开上面的路径")
            return {"ok": True, "data_dir": str(self.root)}
        except (OSError, subprocess.SubprocessError) as exc:
            raise StorageError(f"系统文件管理器不可用：{exc}") from exc

    # ------------------------------------------------------------------
    # 用户
    # ------------------------------------------------------------------
    @staticmethod
    def _user_row(row: sqlite3.Row) -> dict:
        return {
            "user_id": row["user_id"],
            "nickname": row["nickname"],
            "avatar": row["avatar"],
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            "status": row["status"],
            "is_system": bool(row["is_system"]),
        }

    def list_users(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE status != 'deleted' ORDER BY is_system ASC, "
                "COALESCE(last_used_at, created_at) DESC, created_at ASC"
            ).fetchall()
        return [self._user_row(row) for row in rows]

    def get_user(self, user_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)).fetchone()
        return self._user_row(row) if row else None

    def ensure_user(self, user_id: str) -> dict:
        user = self.get_user(user_id)
        if not user or user["status"] != "active":
            raise StorageError("个人档案不存在或已停用")
        return user

    def create_user(self, nickname: str, avatar: str = "frog", system: bool = False) -> dict:
        nickname = str(nickname or "").strip()
        if not (1 <= len(nickname) <= 20):
            raise StorageError("昵称需要 1–20 个字符")
        avatar = str(avatar or "frog")
        if avatar not in AVATARS:
            avatar = "frog"
        with self.lock, self._db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM users WHERE status != 'deleted'").fetchone()[0]
            if count >= MAX_PROFILES and not system:
                raise StorageError(f"最多创建 {MAX_PROFILES} 个个人档案")
            uid = "u_" + uuid.uuid4().hex[:12]
            now = _now()
            conn.execute(
                "INSERT INTO users(user_id,nickname,avatar,created_at,last_used_at,status,is_system) "
                "VALUES(?,?,?,?,?,?,?)",
                (uid, nickname, avatar, now, now, "archived" if system else "active", 1 if system else 0),
            )
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        return self._user_row(row)

    def update_user(self, user_id: str, nickname: Optional[str] = None,
                    avatar: Optional[str] = None, status: Optional[str] = None) -> dict:
        current = self.ensure_user(user_id)
        sets, values = [], []
        if nickname is not None:
            nickname = str(nickname).strip()
            if not (1 <= len(nickname) <= 20):
                raise StorageError("昵称需要 1–20 个字符")
            sets.append("nickname = ?")
            values.append(nickname)
        if avatar is not None:
            if avatar not in AVATARS:
                raise StorageError("未知头像")
            sets.append("avatar = ?")
            values.append(avatar)
        if status is not None:
            if status not in ("active", "archived"):
                raise StorageError("档案状态只能是 active 或 archived")
            sets.append("status = ?")
            values.append(status)
        if not sets:
            return current
        values.append(str(user_id))
        with self.lock, self._db() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", values)
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)).fetchone()
        return self._user_row(row)

    def touch_user(self, user_id: str) -> None:
        try:
            with self.lock, self._db() as conn:
                conn.execute("UPDATE users SET last_used_at = ? WHERE user_id = ?", (_now(), str(user_id)))
        except Exception:
            pass

    def delete_user(self, user_id: str, confirm: bool = False) -> dict:
        if not confirm:
            raise StorageError("删除个人档案需要明确确认")
        user = self.get_user(user_id)
        if not user:
            raise StorageError("个人档案不存在")
        if user["is_system"]:
            raise StorageError("系统历史档案不能直接删除；请先确认归属")
        with self.lock, self._db() as conn:
            sessions = [r["session_id"] for r in conn.execute(
                "SELECT session_id FROM sessions WHERE user_id = ?", (str(user_id),)).fetchall()]
            recordings = [r["path"] for r in conn.execute(
                "SELECT path FROM recordings WHERE user_id = ?", (str(user_id),)).fetchall()]
            conn.execute("DELETE FROM users WHERE user_id = ?", (str(user_id),))
        for sid in sessions:
            try:
                (self.reports_dir / f"{sid}.json").unlink(missing_ok=True)
            except OSError:
                pass
        for raw in recordings:
            try:
                p = Path(raw).resolve()
                if self.recordings_dir.resolve() in p.parents:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True, "deleted_user": user_id, "reports_removed": len(sessions),
                "recordings_removed": len(recordings),
                "backups_note": "已创建的备份没有被自动删除；备份可能仍包含删除前的档案数据。"}

    # ------------------------------------------------------------------
    # 校准 / 设置 / 资产
    # ------------------------------------------------------------------
    def add_calibration(self, user_id: str, data: dict, session_id: Optional[str] = None,
                        source: Optional[dict] = None, kind: Optional[str] = None) -> dict:
        self.ensure_user(user_id)
        cid = "cal_" + uuid.uuid4().hex[:12]
        at_ms = int(data.get("calibrated_at_ms") or _now_ms())
        tz_offset = data.get("timezone_offset_min")
        at = (datetime.fromtimestamp(at_ms / 1000, tz=timezone(timedelta(minutes=-int(tz_offset)))).isoformat(timespec="seconds")
              if tz_offset is not None else
              datetime.fromtimestamp(at_ms / 1000).astimezone().isoformat(timespec="seconds"))
        range_ = data.get("range") or {}
        quantiles = data.get("quantiles") or {}
        source = source or {}
        q10 = quantiles.get("q10", quantiles.get("q15"))
        q90 = quantiles.get("q90", quantiles.get("q85"))
        source_name = source.get("name") or str(data.get("source_name") or "")
        dev_key = str(data.get("device_key") or calibration_device_key(source_name, source))
        cal_date = str(data.get("calibration_date") or local_date(at_ms, tz_offset))
        status = str(data.get("status") or ("legacy" if data.get("protocol_version") != PROTOCOL_VERSION else "ok"))
        with self.lock, self._db() as conn:
            conn.execute(
                "INSERT INTO calibrations(calibration_id,user_id,session_id,kind,baseline,q10,q50,q90,"
                "range_low,range_high,calibrated_at,calibrated_at_ms,calibration_date,timezone_offset_min,"
                "device_key,method,source_name,source_info,n_frames,signal_quality,protocol_version,"
                "mapping_version,stages_json,effective_sec,elapsed_sec,status,algorithm_version,params_version)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, str(user_id), session_id, str(kind or data.get("kind") or "daily"),
                 float(data.get("baseline") or 0.5),
                 _num(q10), _num(quantiles.get("q50")), _num(q90),
                 _num(range_.get("low")), _num(range_.get("high")), at, at_ms, cal_date, tz_offset,
                 dev_key, str(data.get("range_mode") or data.get("method") or "daily_v2"),
                 source_name, _json(source), int(data.get("n_frames") or 0),
                 _json(data.get("signal_quality") or {}),
                 str(data.get("protocol_version") or "legacy"),
                 str(data.get("mapping_version") or "legacy"),
                 _json(data.get("stages") or {}), float(data.get("effective_sec") or 0),
                 float(data.get("elapsed_sec") or 0), status,
                 str(data.get("algorithm_version") or "focus_engine_v1.8.2"), "v1.8.2"),
            )
            row = conn.execute("SELECT * FROM calibrations WHERE calibration_id = ?", (cid,)).fetchone()
            ref_row = None
            if source_name == "hardware" and status in ("ok", "stretched") and data.get("is_valid", True):
                ref_row = self._ensure_initial_reference(conn, str(user_id), row)
                # 参考基线创建时会回填 calibrations.reference_baseline_id；重新取行，
                # 否则返回给前端的校准对象会少这个指针。
                row = conn.execute("SELECT * FROM calibrations WHERE calibration_id = ?", (cid,)).fetchone()
        result = self._calibration_row(row)
        if ref_row:
            result["reference_baseline_id"] = ref_row["baseline_id"]
        return result

    def _calibration_row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["calibration_id"], "user_id": row["user_id"], "session_id": row["session_id"],
            "kind": row["kind"], "baseline": row["baseline"],
            "quantiles": {"q15": row["q10"], "q50": row["q50"], "q85": row["q90"],
                          "q10": row["q10"], "q90": row["q90"]},
            "range": {"low": row["range_low"], "high": row["range_high"]},
            "at": row["calibrated_at_ms"], "calibrated_at": row["calibrated_at"],
            "calibration_date": row["calibration_date"], "timezone_offset_min": row["timezone_offset_min"],
            "device_key": row["device_key"], "method": row["method"], "source_name": row["source_name"],
            "source": _load_json(row["source_info"], {}), "n_frames": row["n_frames"],
            "signal_quality": _load_json(row["signal_quality"], {}),
            "protocol_version": row["protocol_version"], "mapping_version": row["mapping_version"],
            "stages": _load_json(row["stages_json"], {}), "effective_sec": row["effective_sec"],
            "elapsed_sec": row["elapsed_sec"], "status": row["status"],
            "reference_baseline_id": row["reference_baseline_id"],
            "is_valid": bool(row["is_valid"]),
            "algorithm_version": row["algorithm_version"], "params_version": row["params_version"],
        }

    def latest_calibration(self, user_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM calibrations WHERE user_id = ? AND is_valid = 1 "
                "ORDER BY calibrated_at_ms DESC LIMIT 1", (str(user_id),)
            ).fetchone()
        return self._calibration_row(row) if row else None

    def calibration_history(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM calibrations WHERE user_id = ? ORDER BY calibrated_at_ms DESC LIMIT ?",
                (str(user_id), max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._calibration_row(r) for r in rows]

    def get_calibration(self, user_id: str, calibration_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM calibrations WHERE calibration_id = ? AND user_id = ?",
                (str(calibration_id), str(user_id)),
            ).fetchone()
        return self._calibration_row(row) if row else None

    def calibration_status(self, user_id: str, *, mode: str = "hardware",
                           device: Optional[str] = None, tz_offset_min: Optional[int] = None,
                           now_ms: Optional[int] = None) -> dict:
        self.ensure_user(user_id)
        now = int(now_ms if now_ms is not None else _now_ms())
        history = self.calibration_history(user_id, 80)
        result = daily_status(history, now_ms=now, mode=mode,
                              device=device or calibration_device_key(mode),
                              tz_offset_min=tz_offset_min)
        result["calibration"] = result.get("calibration") or None
        result["history_count"] = len(history)
        result["mode"] = mode
        result["status_text"] = ("今日校准有效" if result["valid"] else {
            "date_changed": "今日尚未校准", "expired": "校准已过期，需要重新校准",
            "device_changed": "设备/信号源已变化，需要重新校准", "missing": "今日尚未校准",
        }.get(result.get("reason"), "需要重新校准"))
        return result

    def _reference_row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["baseline_id"], "user_id": row["user_id"], "label": row["label"],
            "version": row["version"], "baseline": row["baseline"],
            "range": {"low": row["range_low"], "high": row["range_high"]},
            "q15": row["q15"], "q85": row["q85"], "n_frames": row["n_frames"],
            "source": _load_json(row["source_info"], {}), "source_name": None,
            "protocol_version": row["protocol_version"], "mapping_version": row["mapping_version"],
            "device_key": row["device_key"], "stages": _load_json(row["stages_json"], {}),
            "is_initial": bool(row["is_initial"]), "status": row["status"],
            "superseded_by": row["superseded_by"], "is_active": bool(row["is_active"]),
            "algorithm_version": row["algorithm_version"], "created_at": row["created_at"],
        }

    def reference_baselines(self, user_id: str) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM reference_baselines WHERE user_id = ? ORDER BY created_at DESC, rowid DESC",
                (str(user_id),),
            ).fetchall()
        return [self._reference_row(r) for r in rows]

    def reference_baseline(self, user_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM reference_baselines WHERE user_id = ? AND is_active = 1 "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1", (str(user_id),)
            ).fetchone()
        return self._reference_row(row) if row else None

    @staticmethod
    def _ensure_initial_reference(conn: sqlite3.Connection, user_id: str, cal: sqlite3.Row) -> Optional[sqlite3.Row]:
        exists = conn.execute(
            "SELECT * FROM reference_baselines WHERE user_id = ? AND is_active = 1 LIMIT 1", (str(user_id),)
        ).fetchone()
        if exists:
            return exists
        bid = "ref_" + uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO reference_baselines(baseline_id,user_id,label,baseline,range_low,range_high,"
            "valid_from,source_info,algorithm_version,version,q15,q85,n_frames,protocol_version,"
            "mapping_version,device_key,stages_json,is_initial,status,is_active,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bid, str(user_id), "初始长期参考基线", cal["baseline"], cal["range_low"], cal["range_high"],
             cal["calibrated_at"], cal["source_info"], cal["algorithm_version"], "v1",
             cal["q10"], cal["q90"], cal["n_frames"], cal["protocol_version"],
             cal["mapping_version"], cal["device_key"], cal["stages_json"], 1, "active", 1, _now()),
        )
        conn.execute("UPDATE calibrations SET reference_baseline_id = ? WHERE calibration_id = ?",
                     (bid, cal["calibration_id"]))
        return conn.execute("SELECT * FROM reference_baselines WHERE baseline_id = ?", (bid,)).fetchone()

    def add_reference_baseline(self, user_id: str, calibration_id: str, label: Optional[str] = None) -> dict:
        cal = self.get_calibration(user_id, calibration_id)
        if not cal:
            raise StorageError("校准记录不存在或不属于当前档案")
        if cal.get("source_name") != "hardware":
            raise StorageError("只有通过质量检查的真实硬件 EEG 校准才能建立长期参考基线")
        if cal.get("status") not in ("ok", "stretched") or not cal.get("is_valid"):
            raise StorageError("该校准不是有效质量记录，不能建立长期参考基线")
        with self.lock, self._db() as conn:
            rows = conn.execute(
                "SELECT version FROM reference_baselines WHERE user_id = ?", (str(user_id),)
            ).fetchall()
            version = "v" + str(len(rows) + 1)
            bid = "ref_" + uuid.uuid4().hex[:12]
            conn.execute(
                "UPDATE reference_baselines SET is_active = 0, status = 'superseded', superseded_by = ? "
                "WHERE user_id = ? AND is_active = 1", (bid, str(user_id)),
            )
            conn.execute(
                "INSERT INTO reference_baselines(baseline_id,user_id,label,baseline,range_low,range_high,"
                "valid_from,source_info,algorithm_version,version,q15,q85,n_frames,protocol_version,"
                "mapping_version,device_key,stages_json,is_initial,status,is_active,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bid, str(user_id), label or f"长期参考基线 {version}", cal["baseline"],
                 cal["range"]["low"], cal["range"]["high"], cal["calibrated_at"], _json(cal["source"]),
                 cal["algorithm_version"], version, cal["quantiles"].get("q15"),
                 cal["quantiles"].get("q85"), cal["n_frames"], cal["protocol_version"],
                 cal["mapping_version"], cal["device_key"], _json(cal["stages"]), 0, "active", 1, _now()),
            )
            conn.execute("UPDATE calibrations SET reference_baseline_id = ? WHERE calibration_id = ?",
                         (bid, calibration_id))
            row = conn.execute("SELECT * FROM reference_baselines WHERE baseline_id = ?", (bid,)).fetchone()
        return self._reference_row(row)

    def wallet(self, user_id: str) -> dict:
        with self._db() as conn:
            row = conn.execute("SELECT wallet_balance, wallet_meta FROM users WHERE user_id = ?", (str(user_id),)).fetchone()
        if not row:
            raise StorageError("个人档案不存在")
        meta = _load_json(row["wallet_meta"], {}) or {}
        return {"v": 1, "points": int(row["wallet_balance"]), "rounds": int(meta.get("rounds") or 0),
                "jumps": int(meta.get("jumps") or 0), "spent": int(meta.get("spent") or 0)}

    def _set_wallet(self, conn: sqlite3.Connection, user_id: str, wallet: dict) -> dict:
        points = max(0, int(wallet.get("points") or 0))
        meta = {"rounds": max(0, int(wallet.get("rounds") or 0)),
                "jumps": max(0, int(wallet.get("jumps") or 0)),
                "spent": max(0, int(wallet.get("spent") or 0))}
        conn.execute("UPDATE users SET wallet_balance = ?, wallet_meta = ? WHERE user_id = ?",
                     (points, _json(meta), str(user_id)))
        return {"v": 1, "points": points, **meta}

    def sync_state(self, user_id: str, payload: dict) -> dict:
        self.ensure_user(user_id)
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        wallet = payload.get("wallet") if isinstance(payload.get("wallet"), dict) else None
        owned = payload.get("owned") if isinstance(payload.get("owned"), list) else None
        outfits = payload.get("outfits") if isinstance(payload.get("outfits"), dict) else None
        achievements = payload.get("achievements") if isinstance(payload.get("achievements"), dict) else None
        # 限制单次状态大小，避免把脑电/二进制误传到设置表
        serialized = _json(payload)
        if len(serialized.encode("utf-8")) > 2_000_000:
            raise StorageError("状态数据过大，未保存")
        with self.lock, self._db() as conn:
            for key, value in list(settings.items())[:100]:
                if not str(key).startswith("bf-") or len(str(key)) > 80:
                    continue
                conn.execute(
                    "INSERT INTO user_settings(user_id,setting_key,value_json,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(user_id,setting_key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (str(user_id), str(key), _json(value), _now()),
                )
            now = _now()
            if owned is not None:
                ids = [str(x) for x in owned if isinstance(x, str) and len(x) <= 80][:2000]
                conn.execute("DELETE FROM inventories WHERE user_id = ? AND kind = 'shop'", (str(user_id),))
                for item_id in ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO inventories(user_id,item_id,kind,acquired_at,metadata_json) "
                        "VALUES(?,?,?,?,?)", (str(user_id), item_id, "shop", now, "{}"),
                    )
            if outfits is not None:
                for key, value in list(outfits.items())[:20]:
                    if isinstance(key, str) and len(key) <= 60:
                        conn.execute(
                            "INSERT INTO user_settings(user_id,setting_key,value_json,updated_at) VALUES(?,?,?,?) "
                            "ON CONFLICT(user_id,setting_key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                            (str(user_id), "bf-outfit." + key, _json(value), now),
                        )
            if achievements is not None:
                unlocked = achievements.get("unlocked") if isinstance(achievements.get("unlocked"), dict) else achievements
                if isinstance(unlocked, dict):
                    for aid, ts in list(unlocked.items())[:1000]:
                        if isinstance(aid, str) and len(aid) <= 80:
                            stamp = _iso_from_ms(ts) if isinstance(ts, (int, float)) else (str(ts) if ts else now)
                            conn.execute(
                                "INSERT INTO achievements(user_id,achievement_id,unlocked_at) VALUES(?,?,?) "
                                "ON CONFLICT(user_id,achievement_id) DO UPDATE SET unlocked_at=COALESCE(achievements.unlocked_at, excluded.unlocked_at)",
                                (str(user_id), aid, stamp),
                            )
            current_row = conn.execute("SELECT wallet_balance, wallet_meta FROM users WHERE user_id = ?", (str(user_id),)).fetchone()
            current = {"points": int(current_row["wallet_balance"]), **_load_json(current_row["wallet_meta"], {})}
            if wallet is not None:
                incoming = max(0, int(wallet.get("points") or 0))
                delta = incoming - int(current.get("points") or 0)
                if delta:
                    idem = str(payload.get("idempotency_key") or "").strip()
                    if not idem:
                        digest = hashlib.sha1(_json({"wallet": wallet, "owned": owned}).encode("utf-8")).hexdigest()[:16]
                        idem = f"sync:{user_id}:{digest}"
                    existing = conn.execute(
                        "SELECT transaction_id FROM wallet_transactions WHERE idempotency_key = ?", (idem,)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO wallet_transactions(transaction_id,user_id,amount,kind,session_id,"
                            "idempotency_key,balance_after,created_at) VALUES(?,?,?,?,?,?,?,?)",
                            ("tx_" + uuid.uuid4().hex[:12], str(user_id), delta,
                             "spend" if delta < 0 else "sync", None, idem, incoming, now),
                        )
                self._set_wallet(conn, user_id, wallet)
            # 返回同一事务内的当前状态，避免在未提交事务中另开连接读到旧余额
            wallet_row = conn.execute(
                "SELECT wallet_balance, wallet_meta FROM users WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            wallet_meta = _load_json(wallet_row["wallet_meta"], {}) or {}
            result_wallet = {"v": 1, "points": int(wallet_row["wallet_balance"]),
                             "rounds": int(wallet_meta.get("rounds") or 0),
                             "jumps": int(wallet_meta.get("jumps") or 0),
                             "spent": int(wallet_meta.get("spent") or 0)}
            settings_rows = conn.execute(
                "SELECT setting_key, value_json FROM user_settings WHERE user_id = ?", (str(user_id),)
            ).fetchall()
            inventory = [r["item_id"] for r in conn.execute(
                "SELECT item_id FROM inventories WHERE user_id = ? AND kind = 'shop'", (str(user_id),)
            ).fetchall()]
            ach = [r["achievement_id"] for r in conn.execute(
                "SELECT achievement_id FROM achievements WHERE user_id = ?", (str(user_id),)
            ).fetchall()]
        return {"ok": True, "wallet": result_wallet,
                "settings": {r["setting_key"]: _load_json(r["value_json"], None) for r in settings_rows},
                "owned": inventory, "achievements": ach}

    # ------------------------------------------------------------------
    # v1.8.3 个体自适应难度
    # ------------------------------------------------------------------
    @staticmethod
    def _difficulty_row(row: sqlite3.Row) -> dict:
        return {
            "user_id": row["user_id"],
            "factor": round(float(row["factor"]), 3),
            "auto_enabled": bool(row["auto_enabled"]),
            "manual_lock": bool(row["manual_lock"]),
            "streak_hard": int(row["streak_hard"]),
            "streak_easy": int(row["streak_easy"]),
            "last_decision": row["last_decision"],
            "last_reason": row["last_reason"],
            "last_metrics": _load_json(row["last_metrics_json"], {}) or {},
            "last_session_id": row["last_session_id"],
            "last_calibration_id": row["last_calibration_id"],
            "last_device_key": row["last_device_key"],
            "last_adjusted_at": row["last_adjusted_at"],
            "strategy_version": row["strategy_version"],
            "updated_at": row["updated_at"],
        }

    def _ensure_difficulty_profile(self, conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
        conn.execute(
            "INSERT OR IGNORE INTO difficulty_profiles(user_id,factor,auto_enabled,manual_lock,"
            "streak_hard,streak_easy,last_metrics_json,strategy_version,updated_at) "
            "VALUES(?,?,1,0,0,0,'{}',?,?)",
            (str(user_id), difficulty.CONFIG["default_factor"], difficulty.STRATEGY_VERSION, _now()),
        )
        return conn.execute("SELECT * FROM difficulty_profiles WHERE user_id = ?",
                            (str(user_id),)).fetchone()

    def difficulty_profile(self, user_id: str, *, history_limit: int = 12) -> dict:
        """读取个人难度档；老用户按 1.00 自动迁移，不改动历史 Session。"""
        self.ensure_user(user_id)
        with self.lock, self._db() as conn:
            self._ensure_difficulty_profile(conn, str(user_id))
            row = conn.execute("SELECT * FROM difficulty_profiles WHERE user_id = ?",
                               (str(user_id),)).fetchone()
            history = conn.execute(
                "SELECT * FROM difficulty_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (str(user_id), int(history_limit)),
            ).fetchall()
        out = self._difficulty_row(row)
        out["history"] = [self._difficulty_history_row(r) for r in history]
        out["next_factor"] = out["factor"]
        out["config"] = difficulty.snapshot(
            out["factor"], auto_enabled=out["auto_enabled"],
            manual_lock=out["manual_lock"])
        return out

    @staticmethod
    def _difficulty_history_row(row: sqlite3.Row) -> dict:
        keys = set(row.keys())
        def val(name, default=None):
            return row[name] if name in keys else default
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "session_id": val("session_id"),
            "before_factor": val("before_factor"),
            "after_factor": val("after_factor"),
            "direction": val("direction"),
            "decision": val("decision"),
            "reason": val("reason"),
            "metrics": _load_json(val("metrics_json"), {}) or {},
            "calibration_id": val("calibration_id"),
            "strategy_version": val("strategy_version"),
            "params_version": val("params_version"),
            "source": val("source"),
            "created_at": row["created_at"],
        }

    def begin_difficulty_session(self, user_id: str, *, calibration_id: Optional[str],
                                 device_key: Optional[str]) -> dict:
        """在 Session 创建时锁定难度；校准/设备/策略变化时重置连续判定。"""
        self.ensure_user(user_id)
        current_cal = str(calibration_id or "")
        current_device = str(device_key or "")
        with self.lock, self._db() as conn:
            row = self._ensure_difficulty_profile(conn, str(user_id))
            reset = (
                (row["last_calibration_id"] is not None
                 and str(row["last_calibration_id"]) != current_cal)
                or (row["last_device_key"] is not None
                    and str(row["last_device_key"]) != current_device)
                or (row["strategy_version"] or "") != difficulty.STRATEGY_VERSION
            )
            if reset:
                conn.execute(
                    "UPDATE difficulty_profiles SET streak_hard=0, streak_easy=0, "
                    "last_calibration_id=?, last_device_key=?, updated_at=? WHERE user_id=?",
                    (current_cal, current_device, _now(), str(user_id)),
                )
            else:
                conn.execute(
                    "UPDATE difficulty_profiles SET last_calibration_id=?, last_device_key=?, "
                    "updated_at=? WHERE user_id=?",
                    (current_cal, current_device, _now(), str(user_id)),
                )
            row = conn.execute("SELECT * FROM difficulty_profiles WHERE user_id = ?",
                               (str(user_id),)).fetchone()
        return difficulty.snapshot(
            row["factor"], auto_enabled=bool(row["auto_enabled"]),
            manual_lock=bool(row["manual_lock"]),
            calibration_id=calibration_id, device_key=device_key,
        )

    def difficulty_history(self, user_id: str, limit: int = 20) -> list[dict]:
        self.ensure_user(user_id)
        with self.lock, self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM difficulty_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (str(user_id), int(limit)),
            ).fetchall()
        return [self._difficulty_history_row(r) for r in rows]

    def set_difficulty(self, user_id: str, *, auto_enabled: Optional[bool] = None,
                       manual_lock: Optional[bool] = None, factor: Optional[float] = None,
                       reset: bool = False) -> dict:
        """手动控制只写个人档；已创建 Session 的快照不会被改动。"""
        self.ensure_user(user_id)
        with self.lock, self._db() as conn:
            row = self._ensure_difficulty_profile(conn, str(user_id))
            before = round(float(row["factor"]), 3)
            new_factor = before
            new_auto = bool(row["auto_enabled"])
            new_lock = bool(row["manual_lock"])
            if reset:
                new_factor = difficulty.CONFIG["default_factor"]
                new_lock = False
            if factor is not None:
                new_factor = round(difficulty.clamp(
                    float(factor), difficulty.CONFIG["min_factor"], difficulty.CONFIG["max_factor"]), 3)
                new_lock = True
                new_auto = False
            if manual_lock is not None:
                new_lock = bool(manual_lock)
                if new_lock:
                    new_auto = False
            if auto_enabled is not None:
                new_auto = bool(auto_enabled)
                if new_auto:
                    new_lock = False
            changed = (abs(new_factor - before) > 1e-9
                       or new_auto != bool(row["auto_enabled"])
                       or new_lock != bool(row["manual_lock"]))
            if changed:
                conn.execute(
                    "UPDATE difficulty_profiles SET factor=?, auto_enabled=?, manual_lock=?, "
                    "streak_hard=0, streak_easy=0, updated_at=? WHERE user_id=?",
                    (new_factor, 1 if new_auto else 0, 1 if new_lock else 0,
                     _now(), str(user_id)),
                )
                decision = "MANUAL_RESET" if reset else "MANUAL_CONTROL"
                reason = "恢复标准难度 1.00" if reset else (
                    "手动锁定难度" if new_lock else (
                        "关闭自动适配" if not new_auto else "手动调整难度"))
                conn.execute(
                    "INSERT INTO difficulty_history(user_id,session_id,config_json,reason,created_at,"
                    "before_factor,after_factor,direction,decision,metrics_json,calibration_id,"
                    "strategy_version,params_version,source) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(user_id), None, _json(difficulty.snapshot(
                        new_factor, auto_enabled=new_auto, manual_lock=new_lock)),
                     reason, _now(), before, new_factor, "hold", decision, "{}",
                     row["last_calibration_id"], difficulty.STRATEGY_VERSION,
                     difficulty.PARAMS_VERSION, "manual"),
                )
            row = conn.execute("SELECT * FROM difficulty_profiles WHERE user_id = ?",
                               (str(user_id),)).fetchone()
        out = self._difficulty_row(row)
        out["changed"] = changed
        out["next_factor"] = out["factor"]
        return out

    def record_difficulty(self, report: dict, user_id: Optional[str] = None) -> dict:
        """局后评估；唯一 session_id 保证重复结算不重复调整。"""
        sid = str(report.get("session_id") or "")
        source = report.get("source") or {}
        source_name = str(source.get("name") or report.get("source_name") or "unknown")
        if not user_id or not sid:
            return {"applied": False, "reason": "no_user_or_session"}
        if source_name != "hardware" or report.get("demo") or report.get("purpose") != "game":
            # 回放、手动、心率、试玩与测试源绝不写真实儿童难度档案。
            return {"applied": False, "reason": "source_isolated", "source": source_name}
        snap = report.get("difficulty_snapshot") or {}
        used_factor = difficulty.clamp(
            float(snap.get("factor") if snap.get("factor") is not None
                  else difficulty.CONFIG["default_factor"]),
            difficulty.CONFIG["min_factor"], difficulty.CONFIG["max_factor"])
        metrics = difficulty.compute_metrics(report)
        with self.lock, self._db() as conn:
            duplicate = conn.execute(
                "SELECT * FROM difficulty_history WHERE session_id = ?", (sid,)).fetchone()
            if duplicate:
                profile = self._difficulty_row(self._ensure_difficulty_profile(conn, str(user_id)))
                return {"applied": False, "duplicate": True, "profile": profile,
                        "decision": duplicate["decision"]}
            row = self._ensure_difficulty_profile(conn, str(user_id))
            # 游戏进行中若发生过手动改档，不能再用旧 Session 覆盖新设置。
            if abs(float(row["factor"]) - used_factor) > 1e-9:
                profile = self._difficulty_row(row)
                return {"applied": False, "reason": "profile_changed_during_session",
                        "profile": profile}
            plan = difficulty.decide(
                metrics, factor=used_factor, auto_enabled=bool(row["auto_enabled"]),
                manual_lock=bool(row["manual_lock"]),
                streak_hard=int(row["streak_hard"]), streak_easy=int(row["streak_easy"]),
            )
            adjusted_at = _now()
            conn.execute(
                "UPDATE difficulty_profiles SET factor=?, streak_hard=?, streak_easy=?, "
                "last_decision=?, last_reason=?, last_metrics_json=?, last_session_id=?, "
                "last_adjusted_at=?, updated_at=? WHERE user_id=?",
                (plan["next_factor"], plan["streak_hard"], plan["streak_easy"],
                 plan["decision"], plan["reason"], _json(metrics), sid,
                 adjusted_at if plan["changed"] else row["last_adjusted_at"], adjusted_at,
                 str(user_id)),
            )
            conn.execute(
                "INSERT INTO difficulty_history(user_id,session_id,config_json,reason,created_at,"
                "before_factor,after_factor,direction,decision,metrics_json,calibration_id,"
                "strategy_version,params_version,source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(user_id), sid, _json(snap), plan["reason"], adjusted_at,
                 plan["current_factor"], plan["next_factor"], plan["direction"],
                 plan["decision"], _json(metrics), report.get("calibration_id"),
                 difficulty.STRATEGY_VERSION, difficulty.PARAMS_VERSION, source_name),
            )
            profile = self._difficulty_row(conn.execute(
                "SELECT * FROM difficulty_profiles WHERE user_id = ?", (str(user_id),)
            ).fetchone())
        out = dict(plan)
        out["applied"] = plan["changed"]
        out["profile"] = profile
        out["metrics"] = metrics
        return out

    # ------------------------------------------------------------------
    # v1.8.4 标准评估
    # ------------------------------------------------------------------
    @staticmethod
    def _assessment_row(row: sqlite3.Row) -> dict:
        return {
            "assessment_id": row["assessment_id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "protocol_version": row["protocol_version"],
            "planned_sec": row["planned_sec"],
            "fixed_factor": row["fixed_factor"],
            "seed": row["seed"],
            "status": row["status"],
            "simulation": bool(row["simulation"]),
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "calibration_id": row["calibration_id"],
            "reference_baseline_id": row["reference_baseline_id"],
            "device": _load_json(row["device_json"], {}) or {},
            "params": _load_json(row["params_json"], {}) or {},
            "features": _load_json(row["features_json"], {}) or {},
            "behavior": _load_json(row["behavior_json"], {}) or {},
            "report": _load_json(row["report_json"], {}) or {},
            "created_at": row["created_at"],
        }

    def create_assessment(self, user_id: Optional[str], session_id: str, *,
                          protocol_version: str = "standard_v1", planned_sec: float = 90.0,
                          seed: Optional[str] = None, simulation: bool = False,
                          calibration_id: Optional[str] = None,
                          reference_baseline_id: Optional[str] = None,
                          device: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        """为已创建的 Session 建立标准评估记录；session_id 唯一，重复创建直接返回原记录。"""
        sid = str(session_id or "").strip()
        if not sid:
            raise StorageError("评估缺少 session_id")
        if user_id:
            self.ensure_user(user_id)
        aid = "asm_" + uuid.uuid4().hex[:12]
        now = _now()
        with self.lock, self._db() as conn:
            row = conn.execute("SELECT * FROM assessments WHERE session_id = ?", (sid,)).fetchone()
            if row:
                return self._assessment_row(row)
            conn.execute(
                "INSERT INTO assessments(assessment_id,user_id,session_id,protocol_version,planned_sec,"
                "fixed_factor,seed,status,simulation,started_at,calibration_id,reference_baseline_id,"
                "device_json,params_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, user_id, sid, str(protocol_version), float(planned_sec), 1.0, seed,
                 "running", 1 if simulation else 0, now, calibration_id, reference_baseline_id,
                 _json(device or {}), _json(params or {}), now),
            )
            row = conn.execute("SELECT * FROM assessments WHERE assessment_id = ?", (aid,)).fetchone()
        return self._assessment_row(row)

    def complete_assessment(self, session_id: str, report: dict) -> Optional[dict]:
        """写入评估结果；以 session_id 幂等，重复 finish 不覆盖已保存报告。"""
        sid = str(session_id or "")
        if not sid:
            return None
        actions = report.get("actions") or {}
        rounds = actions.get("rounds") or []
        inc = actions.get("incomplete_round") or None
        process = report.get("charge_process") or {}
        features = {
            "score_mean": report.get("score_mean"), "score_min": report.get("score_min"),
            "score_max": report.get("score_max"), "score_range": report.get("score_range"),
            "focus_mean": report.get("focus_mean"),
            "reference_score_mean": report.get("reference_score_mean"),
            "valid_signal_ratio": report.get("valid_signal_ratio"),
            "n_frames": report.get("n_frames"), "n_valid_frames": report.get("n_valid_frames"),
            "curve_points": len(report.get("curve") or []),
        }
        behavior = {
            "rounds": len(rounds), "incomplete_round": inc,
            "successful_jumps": actions.get("successful_jumps"),
            "missed_jumps": actions.get("missed_jumps"),
            "early_taps": actions.get("early_taps"),
            "cooldown_sec": actions.get("cooldown_sec"),
            "charge_process": process,
        }
        with self.lock, self._db() as conn:
            row = conn.execute("SELECT * FROM assessments WHERE session_id = ?", (sid,)).fetchone()
            if not row:
                return None
            if row["status"] == "completed":
                return self._assessment_row(row)
            conn.execute(
                "UPDATE assessments SET status='completed', ended_at=?, features_json=?, "
                "behavior_json=?, report_json=? WHERE session_id=?",
                (_now(), _json(features), _json(behavior), _json(report), sid),
            )
            row = conn.execute("SELECT * FROM assessments WHERE session_id = ?", (sid,)).fetchone()
        return self._assessment_row(row)

    def assessments(self, user_id: Optional[str], limit: int = 30) -> list[dict]:
        with self._db() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM assessments WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (str(user_id), max(1, min(int(limit), 200))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM assessments ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (max(1, min(int(limit), 200)),),
                ).fetchall()
        return [self._assessment_row(r) for r in rows]

    def assessment(self, assessment_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM assessments WHERE assessment_id = ?",
                               (str(assessment_id),)).fetchone()
        if not row:
            return None
        if user_id and row["user_id"] and str(row["user_id"]) != str(user_id):
            raise StorageError("无权访问其他用户的评估")
        return self._assessment_row(row)

    # ------------------------------------------------------------------
    # 游戏记录
    # ------------------------------------------------------------------
    def persist_session(self, report: dict, user_id: Optional[str] = None,
                        calibration_id: Optional[str] = None) -> dict:
        sid = str(report.get("session_id") or "")
        if not sid:
            raise StorageError("报告缺少 session_id")
        if user_id:
            # 系统历史档案状态是 archived，但允许导入报告；普通档案必须是 active。
            owner = self.get_user(user_id)
            if not owner or (owner["status"] != "active" and not owner["is_system"]):
                raise StorageError("个人档案不存在或已停用")
        score = report.get("score")
        demo = bool(report.get("demo"))
        purpose = str(report.get("purpose") or "game")
        assessment_id = report.get("assessment_id")
        earned = 0
        # 标准评估不发放商城积分；它仍可作为本地历史记录读取。
        if user_id and not demo and purpose != "assessment" and score is not None:
            try:
                earned = max(1, int(float(score)) // 30) if float(score) > 0 else 0
            except (TypeError, ValueError):
                earned = 0
        actions = report.get("actions") or {}
        rounds = actions.get("rounds") or []
        source = report.get("source") or {}
        started = report.get("created_at")
        ended = _now()
        params = {"score_range": report.get("score_range"), "baseline": report.get("baseline"),
                  "reference_score_range": report.get("reference_score_range")}
        reference_baseline_id = report.get("reference_baseline_id")
        calibration_snapshot = report.get("calibration_snapshot") or report.get("calibration") or {}
        reference_snapshot = report.get("reference_snapshot") or {}
        quality = report.get("signal_quality") or {}
        valid_ratio = None
        if report.get("n_frames"):
            valid_ratio = round(float(report.get("n_valid_frames") or 0) / float(report["n_frames"]), 4)
        with self.lock, self._db() as conn:
            row = conn.execute("SELECT wallet_points FROM sessions WHERE session_id = ?", (sid,)).fetchone()
            already_points = int(row["wallet_points"]) if row else 0
            conn.execute(
                "INSERT INTO sessions(session_id,user_id,started_at,ended_at,duration_sec,played_sec,"
                "calibration_id,reference_baseline_id,calibration_snapshot_json,reference_snapshot_json,"
                "algorithm_version,params_json,source_json,demo,total_score,wallet_points,"
                "jumps,successful_jumps,missed_jumps,eeg_base_score,actual_score,valid_signal_ratio,"
                "difficulty_snapshot_json,purpose,assessment_id,report_json,finished,notes,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET ended_at=excluded.ended_at, played_sec=excluded.played_sec, "
                "duration_sec=excluded.duration_sec, report_json=excluded.report_json, finished=1, "
                "total_score=COALESCE(excluded.total_score, sessions.total_score), notes=excluded.notes, "
                "reference_baseline_id=COALESCE(excluded.reference_baseline_id, sessions.reference_baseline_id), "
                "calibration_snapshot_json=excluded.calibration_snapshot_json, "
                "reference_snapshot_json=excluded.reference_snapshot_json, "
                "purpose=excluded.purpose, assessment_id=excluded.assessment_id",
                (sid, user_id, started, ended, report.get("duration_sec"), report.get("played_sec"),
                 calibration_id, reference_baseline_id, _json(calibration_snapshot), _json(reference_snapshot),
                 str(report.get("algorithm_version") or "unknown"), _json(params), _json(source),
                 1 if demo else 0, int(score) if score is not None else None, already_points,
                 actions.get("timed_jumps"), actions.get("successful_jumps"), actions.get("missed_jumps"),
                 report.get("eeg_base_score"), report.get("actual_score"), valid_ratio,
                 _json(report.get("difficulty_snapshot") or {}), purpose, assessment_id,
                 _json(report), 1, report.get("notes"), _now()),
            )
            for idx, rnd in enumerate(rounds):
                if not isinstance(rnd, dict):
                    continue
                rno = rnd.get("round", idx)
                conn.execute(
                    "INSERT INTO rounds(session_id,user_id,round_no,charge_sec,reaction_sec,potential,awarded,"
                    "success,multiplier,mean_score,above_ratio,early_taps,cooldown_count,cooldown_sec,"
                    "eval_sec,charge_active_sec,below_threshold_sec,stale_sec,decay_events,decay_sec,"
                    "energy_gain,energy_loss,bullet_sec,jump_anim_sec,paused_sec,raw_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id,round_no) DO UPDATE SET "
                    "charge_sec=excluded.charge_sec,reaction_sec=excluded.reaction_sec,potential=excluded.potential,"
                    "awarded=excluded.awarded,success=excluded.success,multiplier=excluded.multiplier,"
                    "mean_score=excluded.mean_score,above_ratio=excluded.above_ratio,early_taps=excluded.early_taps,"
                    "cooldown_count=excluded.cooldown_count,cooldown_sec=excluded.cooldown_sec,"
                    "eval_sec=excluded.eval_sec,charge_active_sec=excluded.charge_active_sec,"
                    "below_threshold_sec=excluded.below_threshold_sec,stale_sec=excluded.stale_sec,"
                    "decay_events=excluded.decay_events,decay_sec=excluded.decay_sec,"
                    "energy_gain=excluded.energy_gain,energy_loss=excluded.energy_loss,"
                    "bullet_sec=excluded.bullet_sec,jump_anim_sec=excluded.jump_anim_sec,"
                    "paused_sec=excluded.paused_sec,raw_json=excluded.raw_json",
                    (sid, user_id, rno, rnd.get("charge_sec"), rnd.get("reaction_sec"), rnd.get("potential"),
                     rnd.get("awarded"), 1 if rnd.get("success") else 0, rnd.get("multiplier"),
                     rnd.get("mean_score"), rnd.get("above_ratio"), rnd.get("early_taps"),
                     rnd.get("cooldown_count"), rnd.get("cooldown_sec"), rnd.get("eval_sec"),
                     rnd.get("charge_active_sec"), rnd.get("below_threshold_sec"), rnd.get("stale_sec"),
                     rnd.get("decay_events"), rnd.get("decay_sec"), rnd.get("energy_gain"),
                     rnd.get("energy_loss"), rnd.get("bullet_sec"), rnd.get("jump_anim_sec"),
                     rnd.get("paused_sec"), _json(rnd)),
                )
            if user_id:
                if purpose != "assessment":
                    self._apply_session_wallet(conn, user_id, sid, earned, demo)
                conn.execute("UPDATE sessions SET wallet_points = ? WHERE session_id = ?", (earned, sid))
                conn.execute("UPDATE users SET last_used_at = ? WHERE user_id = ?", (_now(), user_id))
                wallet_row = conn.execute(
                    "SELECT wallet_balance, wallet_meta FROM users WHERE user_id = ?", (str(user_id),)
                ).fetchone()
                wallet_meta = _load_json(wallet_row["wallet_meta"], {}) or {}
                result = {"v": 1, "points": int(wallet_row["wallet_balance"]),
                          "rounds": int(wallet_meta.get("rounds") or 0),
                          "jumps": int(wallet_meta.get("jumps") or 0),
                          "spent": int(wallet_meta.get("spent") or 0)}
            else:
                result = None
        # 用户主动导出的报告落在数据目录；数据库仍是主索引
        try:
            (self.reports_dir / f"{sid}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        return {"wallet": result, "earned_points": earned}

    def _apply_session_wallet(self, conn: sqlite3.Connection, user_id: str, session_id: str,
                              earned: int, demo: bool) -> None:
        if demo or earned <= 0:
            return
        idem = f"session:{session_id}"
        if conn.execute("SELECT 1 FROM wallet_transactions WHERE idempotency_key = ?", (idem,)).fetchone():
            return
        row = conn.execute("SELECT wallet_balance, wallet_meta FROM users WHERE user_id = ?", (user_id,)).fetchone()
        balance = int(row["wallet_balance"]) + int(earned)
        meta = _load_json(row["wallet_meta"], {}) or {}
        meta["rounds"] = int(meta.get("rounds") or 0) + 1
        meta["jumps"] = int(meta.get("jumps") or 0) + int(earned)
        conn.execute("UPDATE users SET wallet_balance = ?, wallet_meta = ? WHERE user_id = ?",
                     (balance, _json(meta), str(user_id)))
        conn.execute(
            "INSERT INTO wallet_transactions(transaction_id,user_id,amount,kind,session_id,idempotency_key,balance_after,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("tx_" + uuid.uuid4().hex[:12], str(user_id), int(earned), "session_reward", session_id, idem, balance, _now()),
        )

    def list_sessions(self, user_id: Optional[str], limit: int = 20) -> list[dict]:
        with self._db() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT session_id, started_at, ended_at, duration_sec, played_sec, total_score, "
                    "wallet_points, finished, source_json, report_json, demo, purpose, assessment_id "
                    "FROM sessions WHERE user_id = ? AND finished = 1 ORDER BY ended_at DESC LIMIT ?", (str(user_id), int(limit))
                ).fetchall()
            else:
                rows = []
        out = []
        for row in rows:
            item = dict(row)
            item["source"] = _load_json(item.pop("source_json", None), {})
            item["report"] = _load_json(item.pop("report_json", None), {})
            out.append(item)
        return out

    def load_report(self, session_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute("SELECT user_id, report_json FROM sessions WHERE session_id = ?",
                               (str(session_id),)).fetchone()
        if not row:
            return None
        if row["user_id"] and user_id != row["user_id"]:
            raise StorageError("无权访问其他用户的报告")
        return _load_json(row["report_json"], None)

    def report_owner(self, session_id: str) -> Optional[str]:
        with self._db() as conn:
            row = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (str(session_id),)).fetchone()
        return row["user_id"] if row else None

    # ------------------------------------------------------------------
    # 旧数据迁移
    # ------------------------------------------------------------------
    def legacy_user(self) -> dict:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM users WHERE is_system = 1 AND status = 'archived' LIMIT 1").fetchone()
        if row:
            return self._user_row(row)
        return self.create_user("历史记录（未归属）", "snail", system=True)

    def import_legacy_reports(self, directory: Optional[Path] = None) -> int:
        directory = Path(directory or "outputs/sessions")
        if not directory.is_dir():
            return 0
        imported = 0
        legacy = self.legacy_user()
        for path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict) or not raw.get("session_id"):
                continue
            # 旧目录里常有回放/演示/0 秒测试报告；不导入，避免污染真实历史档案。
            source_name = (raw.get("source") or {}).get("name")
            if raw.get("demo") or source_name not in ("hardware", "heart") or float(raw.get("played_sec") or 0) <= 0:
                continue
            key = "report:" + path.name
            with self._db() as conn:
                if conn.execute("SELECT 1 FROM legacy_imports WHERE import_key = ?", (key,)).fetchone():
                    continue
            # 旧数据只进入系统历史档案，绝不自动塞进真实儿童档案。
            # 未归属的旧报告统一标记 demo，避免迁移时凭空发放商城积分。
            raw["demo"] = True
            try:
                self.persist_session(raw, legacy["user_id"], None)
                with self._db() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO legacy_imports(import_key,kind,detail,imported_at) VALUES(?,?,?,?)",
                        (key, "report", _json({"source": str(path), "system_user": legacy["user_id"]}), _now()),
                    )
                imported += 1
            except Exception:
                continue
        return imported

    def import_browser_legacy(self, user_id: str, payload: dict) -> dict:
        self.ensure_user(user_id)
        digest = hashlib.sha1(_json(payload).encode("utf-8")).hexdigest()[:16]
        key = f"localstorage:{user_id}:{digest}"
        with self._db() as conn:
            if conn.execute("SELECT 1 FROM legacy_imports WHERE import_key = ?", (key,)).fetchone():
                return {"ok": True, "already_imported": True, "user_id": user_id}
        backup = self.backup("before-browser-legacy-import")
        wallet = payload.get("wallet") if isinstance(payload.get("wallet"), dict) else None
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        # 浏览器旧数据是明确由操作者选择目标档案后才导入的；不复制到所有档案。
        if settings:
            self.sync_state(user_id, {"settings": settings, "wallet": wallet,
                                      "owned": payload.get("owned") or [],
                                      "achievements": payload.get("achievements") or {}})
        calib = payload.get("calibration")
        calibration_id = None
        if isinstance(calib, dict) and calib.get("baseline") is not None:
            calibration_id = self.add_calibration(user_id, calib, source=calib.get("source"))["id"]
        with self._db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO legacy_imports(import_key,kind,detail,imported_at) VALUES(?,?,?,?)",
                (key, "browser", _json({"user_id": user_id, "backup": backup["filename"]}), _now()),
            )
        return {"ok": True, "already_imported": False, "backup": backup["filename"],
                "calibration_id": calibration_id, "user_id": user_id}

    # ------------------------------------------------------------------
    # 桌面启动展示
    # ------------------------------------------------------------------
    def bootstrap(self, user_id: str) -> dict:
        user = self.ensure_user(user_id)
        with self._db() as conn:
            settings_rows = conn.execute(
                "SELECT setting_key, value_json FROM user_settings WHERE user_id = ?", (str(user_id),)
            ).fetchall()
            owned = [r["item_id"] for r in conn.execute(
                "SELECT item_id FROM inventories WHERE user_id = ? AND kind = 'shop'", (str(user_id),)
            ).fetchall()]
            achievements = [dict(r) for r in conn.execute(
                "SELECT achievement_id, unlocked_at, seen FROM achievements WHERE user_id = ?", (str(user_id),)
            ).fetchall()]
        return {
            "user": user,
            "wallet": self.wallet(user_id),
            "settings": {r["setting_key"]: _load_json(r["value_json"], None) for r in settings_rows},
            "owned": owned,
            "achievements": achievements,
            "calibration": self.latest_calibration(user_id),
            "calibration_status": self.calibration_status(user_id),
            "reference_baseline": self.reference_baseline(user_id),
            "difficulty": self.difficulty_profile(user_id),
            "calibration_history": self.calibration_history(user_id, 12),
            "recent_sessions": self.list_sessions(user_id, 6),
            "data_dir": str(self.root),
            "encrypted": False,
        }


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_from_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return _now()


# 全局实例：API 与命令行测试共享；测试可通过 FOCUS_FROG_DATA_DIR 隔离。
storage = StorageManager()
