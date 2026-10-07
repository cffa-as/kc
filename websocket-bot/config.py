"""配置文件管理"""

import json
import os
import tempfile
from typing import Any


class Config:
    """配置管理器"""

    def __init__(self, config_file: str = None):
        self.config_file = config_file or self._get_config_path()
        self._cache = None

    def _get_config_path(self) -> str:
        """获取配置文件路径"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    def load(self) -> dict:
        """加载配置"""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
                return self._cache
        except Exception:
            self._cache = {}
            return self._cache

    def save(self, config: dict):
        """保存配置"""
        try:
            directory = os.path.dirname(os.path.abspath(self.config_file))
            fd, temp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.config_file)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            self._cache = config
        except Exception as e:
            raise IOError(f"保存配置失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        if self._cache is None:
            self.load()
        return self._cache.get(key, default)

    def set(self, key: str, value: Any):
        """设置配置项"""
        if self._cache is None:
            self.load()
        self._cache[key] = value
        self.save(self._cache)

    def delete(self, key: str):
        """删除配置项"""
        if self._cache is None:
            self.load()
        if key in self._cache:
            del self._cache[key]
            self.save(self._cache)


def get_u_param(_name: str = "u") -> str:
    """读取抓包程序同步到配置中的统一 URL u 参数。"""
    config = Config()
    value = config.get("u", "")
    if not value:
        params = config.get("u_params", {})
        value = (
            params.get(_name)
            or params.get("u")
            or next(iter(params.values()), "")
            if isinstance(params, dict)
            else ""
        )
    return str(value or "")


# 全局配置实例
config = Config()
