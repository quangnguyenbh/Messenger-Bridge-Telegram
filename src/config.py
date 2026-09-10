from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        load_dotenv = import_module("dotenv").load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw.strip())


def _resolve_path(value: Optional[str], default_relative: str) -> Path:
    raw = value or default_relative
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _read_cookie() -> str:
    direct = os.environ.get("FACEBOOK_COOKIE") or os.environ.get("MESSENGER_COOKIE")
    if direct and direct.strip():
        return direct.strip()

    cookie_file = os.environ.get("FACEBOOK_COOKIE_FILE") or os.environ.get("MESSENGER_COOKIE_FILE")
    if cookie_file and cookie_file.strip():
        path = _resolve_path(cookie_file, cookie_file)
        if not path.exists():
            raise RuntimeError(f"Cookie file does not exist: {path}")
        return path.read_text(encoding="utf-8").strip()

    raise RuntimeError("Set FACEBOOK_COOKIE or FACEBOOK_COOKIE_FILE in .env")


@dataclass(frozen=True)
class AppConfig:
    log_level: str
    telegram_token: str
    telegram_group_id: int
    facebook_cookie: str
    data_dir: Path
    store_path: Path
    fbchat_e2ee_bin: Optional[str]
    fbchat_e2ee_device_path: Optional[str]
    fbchat_e2ee_log_level: str
    fbchat_e2ee_memory_only: bool
    fbchat_enable_e2ee: bool
    fbchat_e2ee_ready_timeout: float
    fbchat_e2ee_send_timeout: float
    ignore_self_messages: bool
    message_cache_limit: int
    telegram_connect_timeout: float
    telegram_read_timeout: float
    telegram_write_timeout: float
    telegram_pool_timeout: float
    forward_messenger_reactions: bool
    forward_typing_activity: bool
    forward_read_receipts: bool


def load_config() -> AppConfig:
    _load_dotenv()

    data_dir = _resolve_path(os.environ.get("DATA_DIR"), "data")
    e2ee_bin = os.environ.get("FBCHAT_E2EE_BIN", "").strip() or None

    return AppConfig(
        log_level=os.environ.get("LOG_LEVEL", "DEBUG").strip().upper() or "DEBUG",
        telegram_token=_required("TG_TOKEN"),
        telegram_group_id=int(_required("TG_GROUP_ID")),
        facebook_cookie=_read_cookie(),
        data_dir=data_dir,
        store_path=data_dir / "bridge-store.json",
        fbchat_e2ee_bin=e2ee_bin,
        fbchat_e2ee_device_path=os.environ.get("FBCHAT_E2EE_DEVICE_PATH") or None,
        fbchat_e2ee_log_level=os.environ.get("FBCHAT_E2EE_LOG_LEVEL", "none"),
        fbchat_e2ee_memory_only=_env_bool("FBCHAT_E2EE_MEMORY_ONLY", True),
        fbchat_enable_e2ee=_env_bool("FBCHAT_ENABLE_E2EE", True),
        fbchat_e2ee_ready_timeout=float(os.environ.get("FBCHAT_E2EE_READY_TIMEOUT", "90")),
        fbchat_e2ee_send_timeout=float(os.environ.get("FBCHAT_E2EE_SEND_TIMEOUT", "180")),
        ignore_self_messages=_env_bool("IGNORE_SELF_MESSAGES", True),
        message_cache_limit=_env_int("MESSAGE_CACHE_LIMIT", 3000),
        telegram_connect_timeout=float(os.environ.get("TG_CONNECT_TIMEOUT", "15")),
        telegram_read_timeout=float(os.environ.get("TG_READ_TIMEOUT", "45")),
        telegram_write_timeout=float(os.environ.get("TG_WRITE_TIMEOUT", "45")),
        telegram_pool_timeout=float(os.environ.get("TG_POOL_TIMEOUT", "30")),
        forward_messenger_reactions=_env_bool("FORWARD_MESSENGER_REACTIONS", True),
        forward_typing_activity=_env_bool("FORWARD_TYPING_ACTIVITY", False),
        forward_read_receipts=_env_bool("FORWARD_READ_RECEIPTS", False),
    )
