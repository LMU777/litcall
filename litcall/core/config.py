"""配置管理 — 单例模式 + 原子读写。

所有模块通过 `from litcall.core import config` 访问配置，
不直接读 config.json。写入通过 temp 文件 + rename 保证原子性。
"""

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from litcall.core.paths import CONFIG_PATH

# ── 模块级缓存 ──
_config: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()


def load_config() -> Dict[str, Any]:
    """加载配置（线程安全，首次加载后缓存）。"""
    global _config
    with _config_lock:
        if _config is not None:
            return deepcopy(_config)
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"config.json 不存在: {CONFIG_PATH}\n"
                f"请从 config.example.json 复制并填入 API Key。"
            )
        _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return deepcopy(_config)


def save_config(cfg: Dict[str, Any]) -> None:
    """原子写回配置（temp 文件 + rename，崩溃安全）。"""
    global _config
    with _config_lock:
        tmp_path = Path(str(CONFIG_PATH) + ".tmp")
        tmp_path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(CONFIG_PATH)
        _config = deepcopy(cfg)


def reload_config() -> Dict[str, Any]:
    """强制重新读取配置文件（绕过缓存）。"""
    global _config
    with _config_lock:
        _config = None
        return load_config()


# 便捷访问：模块级 config 对象（惰性加载）
class _ConfigProxy:
    """惰性加载的配置代理，支持 dict 和属性访问。"""

    def _get(self) -> Dict[str, Any]:
        return load_config()

    def __getitem__(self, key: str) -> Any:
        return self._get()[key]

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self._get()[key]
        except KeyError:
            raise AttributeError(f"config 中没有 '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        return self._get().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._get()

    def __repr__(self) -> str:
        return f"<ConfigProxy keys={list(self._get().keys())}>"


config = _ConfigProxy()
