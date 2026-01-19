"""Radarr HTTP client and integration utilities."""

from pathlib import Path
from typing import Any, Dict, Optional

import requests


class RadarrConfig:
    """Radarr configuration."""
    def __init__(self, url: str, api_key: str, verify_ssl: bool = True, timeout_sec: int = 30, archive_root: Path = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout_sec = timeout_sec
        self.archive_root = archive_root or Path("/")


def radarr_session(cfg: RadarrConfig) -> requests.Session:
    """Create authenticated Radarr session."""
    s = requests.Session()
    s.headers.update({
        "X-Api-Key": cfg.api_key,
        "Accept": "application/json",
        "User-Agent": "archivarr/0.6",
    })
    return s


def radarr_url(cfg: RadarrConfig, path: str) -> str:
    """Build full Radarr API URL."""
    return cfg.url + path


def radarr_request(
    cfg: RadarrConfig,
    s: requests.Session,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    """Generic HTTP request to Radarr API."""
    url = radarr_url(cfg, path)
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


def radarr_get(cfg: RadarrConfig, s: requests.Session, path: str, params: Optional[dict] = None) -> Any:
    """GET request to Radarr API."""
    return radarr_request(cfg, s, "get", path, params=params)


def radarr_post(cfg: RadarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """POST request to Radarr API."""
    return radarr_request(cfg, s, "post", path, payload=payload)


def radarr_put(cfg: RadarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """PUT request to Radarr API."""
    return radarr_request(cfg, s, "put", path, payload=payload)


def health_check(cfg: RadarrConfig) -> Dict[str, Any]:
    """Check Radarr connection status."""
    s = radarr_session(cfg)
    try:
        status = radarr_get(cfg, s, "/api/v3/system/status")
        return {"ok": True, "connected": True, "version": status.get("version", "unknown")}
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}


def get_ready_to_archive_count(cfg: RadarrConfig) -> int:
    """
    Get count of Radarr movies ready to archive.
    
    A movie is ready to archive if:
    - It has a file (hasFile=True)
    - Quality cutoff has been met (qualityCutoffNotMet=False)
    
    Uses Radarr API /api/v3/movie endpoint which returns MovieResource objects
    with fields documented at https://radarr.video/docs/api/
    """
    try:
        s = radarr_session(cfg)
        movie_list = radarr_get(cfg, s, "/api/v3/movie")
        
        # Normalize archive root for comparison
        archive_root_lower = str(cfg.archive_root).rstrip("\\/").lower()
        
        ready_count = 0
        for movie in movie_list:
            # Skip movies already in archive root
            movie_path = (movie.get("path") or "").rstrip("\\/").lower()
            if movie_path.startswith(archive_root_lower):
                continue
            
            has_file = movie.get("hasFile", False)
            # qualityCutoffNotMet=False means cutoff HAS been met
            # Default to cutoff met when field is missing
            cutoff_met = not movie.get("qualityCutoffNotMet", False)
            
            # Only count if has file AND cutoff is met
            if has_file and cutoff_met:
                ready_count += 1
        
        return ready_count
    except Exception:
        return 0


def get_dashboard_stats(cfg: RadarrConfig) -> Dict[str, Any]:
    """
    Get all dashboard statistics for Radarr in a single API call.
    Returns: total_movies, movies_with_files
    """
    try:
        s = radarr_session(cfg)
        movie_list = radarr_get(cfg, s, "/api/v3/movie")
        
        total_movies = len(movie_list)
        movies_with_files = 0
        
        for movie in movie_list:
            # Check if movie has a file
            if movie.get("hasFile", False):
                movies_with_files += 1
        
        return {
            "total": total_movies,
            "with_files": movies_with_files,
        }
    except Exception:
        return {
            "total": 0,
            "with_files": 0,
        }


def get_total_library_count(cfg: RadarrConfig) -> int:
    """Get total count of Radarr movies in the library."""
    try:
        s = radarr_session(cfg)
        movie_list = radarr_get(cfg, s, "/api/v3/movie")
        return len(movie_list)
    except Exception:
        return 0


def get_total_with_files_count(cfg: RadarrConfig) -> int:
    """Get count of Radarr movies that have files."""
    try:
        s = radarr_session(cfg)
        movie_list = radarr_get(cfg, s, "/api/v3/movie")
        
        with_files_count = 0
        for movie in movie_list:
            # Check if movie has a file
            if movie.get("hasFile", False):
                with_files_count += 1
        
        return with_files_count
    except Exception:
        return 0
