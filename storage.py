"""Data persistence utilities for configuration and scan/move activity tracking."""

import configparser
import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_json_file(filepath: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file safely, return None if not found or invalid."""
    try:
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_json_file(filepath: Path, data: Dict[str, Any]) -> None:
    """Save JSON file safely, creating parent directories if needed."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def load_ini(filepath: Path) -> configparser.ConfigParser:
    """Load INI configuration file."""
    cp = configparser.ConfigParser()
    if filepath.exists():
        cp.read(filepath, encoding="utf-8")
    return cp


def save_ini(filepath: Path, cp: configparser.ConfigParser) -> None:
    """Save INI configuration file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        cp.write(f)
