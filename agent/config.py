"""Agent 配置加载"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional, Union
import yaml


def load_config(config_path: Union[str, Path, None] = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    def _resolve(obj):
        if isinstance(obj, dict):
            return {k: _resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve(item) for item in obj]
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            return os.environ.get(obj[2:-1], "")
        return obj

    return _resolve(config)


_config: Optional[dict] = None


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config
