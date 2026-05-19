"""配置文件管理"""

import json
import os
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
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
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


# 全局配置实例
config = Config()
