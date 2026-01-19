"""Sonarr HTTP client and integration utilities."""

from pathlib import Path
from typing import Any, Dict, Optional

import requests


class SonarrConfig:
    """Sonarr configuration."""
    def __init__(self, url: str, api_key: str, verify_ssl: bool = True, timeout_sec: int = 30, archive_root: Path = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout_sec = timeout_sec
        self.archive_root = archive_root or Path("/")


def sonarr_session(cfg: SonarrConfig) -> requests.Session:
    """Create authenticated Sonarr session."""
    s = requests.Session()
    s.headers.update({
        "X-Api-Key": cfg.api_key,
        "Accept": "application/json",
        "User-Agent": "archivarr/0.6",
    })
    return s


def sonarr_url(cfg: SonarrConfig, path: str) -> str:
    """Build full Sonarr API URL."""
    return cfg.url + path


def sonarr_request(
    cfg: SonarrConfig,
    s: requests.Session,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    """Generic HTTP request to Sonarr API."""
    url = sonarr_url(cfg, path)
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


def sonarr_get(cfg: SonarrConfig, s: requests.Session, path: str, params: Optional[dict] = None) -> Any:
    """GET request to Sonarr API."""
    return sonarr_request(cfg, s, "get", path, params=params)


def sonarr_post(cfg: SonarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """POST request to Sonarr API."""
    return sonarr_request(cfg, s, "post", path, payload=payload)


def sonarr_put(cfg: SonarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """PUT request to Sonarr API."""
    return sonarr_request(cfg, s, "put", path, payload=payload)


def health_check(cfg: SonarrConfig) -> Dict[str, Any]:
    """Check Sonarr connection status."""
    s = sonarr_session(cfg)
    try:
        status = sonarr_get(cfg, s, "/api/v3/system/status")
        return {"ok": True, "connected": True, "version": status.get("version", "unknown")}
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}


def get_ready_to_archive_count(cfg: SonarrConfig) -> int:
    """Count Sonarr series ready to archive: monitored, has episodes, ~all desired episodes have files."""
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        
        # Normalize archive root for comparison
        archive_root_lower = str(cfg.archive_root).rstrip("\\/").lower()
        
        ready_count = 0
        for series in series_list:
            if not series.get("monitored", True):
                continue

            # Skip series already in archive root
            series_path = (series.get("path") or "").rstrip("\\/").lower()
            if series_path.startswith(archive_root_lower):
                continue

            stats = series.get("statistics", {})
            if not isinstance(stats, dict):
                continue

            total_episodes = int(stats.get("episodeCount", 0))
            episodes_with_files = int(stats.get("episodeFileCount", 0))

            if episodes_with_files == 0 or total_episodes == 0:
                continue

            pct = (episodes_with_files / total_episodes * 100)
            if pct >= 99.0:
                ready_count += 1
        
        return ready_count
    except Exception:
        return 0


def get_dashboard_stats(cfg: SonarrConfig) -> Dict[str, Any]:
    """
    Get all dashboard statistics for Sonarr in a single API call.
    Returns: total_series, series_with_episodes, total_episodes, episodes_downloaded
    """
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        
        total_series = len(series_list)
        series_with_episodes = 0
        total_episodes = 0
        episodes_downloaded = 0
        
        for series in series_list:
            stats = series.get("statistics", {})
            if isinstance(stats, dict):
                # Series with episodes
                episodes_on_disk = stats.get("episodeCount", 0)
                if episodes_on_disk > 0:
                    series_with_episodes += 1
                
                # Total episodes
                total_episodes += stats.get("episodeCount", 0)
                
                # Episodes downloaded (only from series with episodes)
                if episodes_on_disk > 0:
                    episodes_downloaded += stats.get("episodeFileCount", 0)
        
        return {
            "total": total_series,
            "with_files": series_with_episodes,
            "total_episodes": total_episodes,
            "episodes_downloaded": episodes_downloaded,
        }
    except Exception:
        return {
            "total": 0,
            "with_files": 0,
            "total_episodes": 0,
            "episodes_downloaded": 0,
        }


def get_total_library_count(cfg: SonarrConfig) -> int:
    """Get total count of Sonarr series in the library."""
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        return len(series_list)
    except Exception:
        return 0


def get_total_with_files_count(cfg: SonarrConfig) -> int:
    """Get count of Sonarr series that have episodes (files)."""
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        
        with_files_count = 0
        for series in series_list:
            # Check if series has episodes on disk by checking statistics
            stats = series.get("statistics", {})
            if isinstance(stats, dict):
                # Check if there are episodes on disk
                episodes_on_disk = stats.get("episodeCount", 0)
                if episodes_on_disk > 0:
                    with_files_count += 1
            elif series.get("sizeOnDisk", 0) > 0:
                # Alternative: check total size on disk
                with_files_count += 1
        
        return with_files_count
    except Exception:
        return 0


def get_total_episodes_count(cfg: SonarrConfig) -> int:
    """Get total count of episodes across all Sonarr series."""
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        
        total_episodes = 0
        for series in series_list:
            # Sum up episodes from statistics
            stats = series.get("statistics", {})
            if isinstance(stats, dict):
                total_episodes += stats.get("episodeCount", 0)
        
        return total_episodes
    except Exception:
        return 0


def get_total_episodes_downloaded_count(cfg: SonarrConfig) -> int:
    """Get total count of downloaded episodes across all Sonarr series."""
    try:
        s = sonarr_session(cfg)
        series_list = sonarr_get(cfg, s, "/api/v3/series")
        
        total_downloaded_episodes = 0
        for series in series_list:
            # Sum up episodes that have been downloaded (series has episodes)
            stats = series.get("statistics", {})
            if isinstance(stats, dict):
                # Only count episodes from series that have episodes on disk
                episodes_on_disk = stats.get("episodeCount", 0)
                if episodes_on_disk > 0:
                    # episodeFileCount is the count of episodes with files
                    total_downloaded_episodes += stats.get("episodeFileCount", 0)
        
        return total_downloaded_episodes
    except Exception:
        return 0
