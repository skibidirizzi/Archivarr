"""Lidarr HTTP client and integration utilities."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests


@dataclass
class AppConfig:
    """Application configuration loaded from config.ini"""
    lidarr_url: str
    lidarr_api_key: str
    verify_ssl: bool
    timeout_sec: int

    archive_root: Path

    sleep_between_artists: float
    limit_artists: int

    verbose_log: bool

    # Wanted/missing paging
    missing_page_size: int
    missing_max_pages: int


def lidarr_session(cfg: AppConfig) -> requests.Session:
    """Create authenticated Lidarr session."""
    s = requests.Session()
    s.headers.update({
        "X-Api-Key": cfg.lidarr_api_key,
        "Accept": "application/json",
        "User-Agent": "archivarr/0.6",
    })
    return s


def lidarr_url(cfg: AppConfig, path: str) -> str:
    """Build full Lidarr API URL."""
    return cfg.lidarr_url + path


def lidarr_request(
    cfg: AppConfig,
    s: requests.Session,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    """Generic HTTP request to Lidarr API."""
    url = lidarr_url(cfg, path)
    kwargs = {
        "timeout": cfg.timeout_sec,
        "verify": cfg.verify_ssl,
    }
    if params:
        kwargs["params"] = params
    if payload:
        kwargs["json"] = payload

    if method.lower() == "get":
        r = s.get(url, **kwargs)
    elif method.lower() == "post":
        r = s.post(url, **kwargs)
    elif method.lower() == "put":
        r = s.put(url, **kwargs)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    r.raise_for_status()
    return r.json()


def lidarr_get(cfg: AppConfig, s: requests.Session, path: str, params: Optional[dict] = None) -> Any:
    """GET request to Lidarr API."""
    return lidarr_request(cfg, s, "get", path, params=params)


def lidarr_post(cfg: AppConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """POST request to Lidarr API."""
    return lidarr_request(cfg, s, "post", path, payload=payload)


def lidarr_put(cfg: AppConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """PUT request to Lidarr API."""
    return lidarr_request(cfg, s, "put", path, payload=payload)


def lidarr_command(cfg: AppConfig, s: requests.Session, name: str, **kwargs: Any) -> Any:
    """Execute a Lidarr command."""
    payload = {"name": name}
    payload.update(kwargs)
    return lidarr_post(cfg, s, "/api/v1/command", payload)


def lidarr_pause(cfg: AppConfig, s: requests.Session) -> None:
    """Pause Lidarr automation."""
    try:
        lidarr_command(cfg, s, "PauseApplication")
    except Exception:
        # Not all Lidarr builds may support pause; ignore failures
        pass


def lidarr_resume(cfg: AppConfig, s: requests.Session) -> None:
    """Resume Lidarr automation."""
    try:
        lidarr_command(cfg, s, "ResumeApplication")
    except Exception:
        pass


def health_check(cfg: AppConfig) -> Dict[str, Any]:
    """Check Lidarr connection status."""
    s = lidarr_session(cfg)
    try:
        status = lidarr_get(cfg, s, "/api/v1/system/status")
        return {"ok": True, "connected": True, "version": status.get("version", "unknown")}
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}
