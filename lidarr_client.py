"""Lidarr HTTP client and integration utilities."""

from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from app_config import LidarrServiceConfig

import requests


class LidarrConfig(Protocol):
    lidarr: LidarrServiceConfig
    verify_ssl: bool
    timeout_sec: int

def lidarr_session(cfg: LidarrConfig) -> requests.Session:
    """Create authenticated Lidarr session."""
    s = requests.Session()
    s.headers.update({
        "X-Api-Key": cfg.lidarr.api_key,
        "Accept": "application/json",
        "User-Agent": "archivarr/0.6",
    })
    return s


def lidarr_url(cfg: LidarrConfig, path: str) -> str:
    """Build full Lidarr API URL."""
    return cfg.lidarr.url + path


def lidarr_request(
    cfg: LidarrConfig,
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


def lidarr_get(cfg: LidarrConfig, s: requests.Session, path: str, params: Optional[dict] = None) -> Any:
    """GET request to Lidarr API."""
    return lidarr_request(cfg, s, "get", path, params=params)


def lidarr_post(cfg: LidarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """POST request to Lidarr API."""
    return lidarr_request(cfg, s, "post", path, payload=payload)


def lidarr_put(cfg: LidarrConfig, s: requests.Session, path: str, payload: dict) -> Any:
    """PUT request to Lidarr API."""
    return lidarr_request(cfg, s, "put", path, payload=payload)


def lidarr_command(cfg: LidarrConfig, s: requests.Session, name: str, **kwargs: Any) -> Any:
    """Execute a Lidarr command."""
    payload = {"name": name}
    payload.update(kwargs)
    return lidarr_post(cfg, s, "/api/v1/command", payload)


def lidarr_pause(cfg: LidarrConfig, s: requests.Session) -> None:
    """Pause Lidarr automation."""
    try:
        lidarr_command(cfg, s, "PauseApplication")
    except Exception:
        # Not all Lidarr builds may support pause; ignore failures
        pass


def lidarr_resume(cfg: LidarrConfig, s: requests.Session) -> None:
    """Resume Lidarr automation."""
    try:
        lidarr_command(cfg, s, "ResumeApplication")
    except Exception:
        pass


def health_check(cfg: LidarrConfig) -> Dict[str, Any]:
    """Check Lidarr connection status."""
    s = lidarr_session(cfg)
    try:
        status = lidarr_get(cfg, s, "/api/v1/system/status")
        return {"ok": True, "connected": True, "version": status.get("version", "unknown")}
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}


def get_ready_to_archive_count(cfg: LidarrConfig) -> int:
    """Get count of Lidarr artists ready to archive (all desired tracks acquired, not already archived)."""
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        # Use Lidarr-specific archive root
        if not cfg.lidarr.archive_root:
            raise ValueError("Lidarr archive root not configured")
        archive_root_lower = str(cfg.lidarr.archive_root).rstrip("\\/").lower()
        
        ready_count = 0
        for artist in artists:
            if not artist.get("monitored", True):
                continue
            
            # Skip artists already in archive root
            artist_path = (artist.get("path") or "").rstrip("\\/").lower()
            if artist_path.startswith(archive_root_lower):
                continue
            
            stats = artist.get("statistics", {})
            if not isinstance(stats, dict):
                continue
            
            # Artist is ready if all desired tracks are acquired
            track_file_count = stats.get("trackFileCount", 0)
            percent_of_tracks = stats.get("percentOfTracks", 0)
            
            # Must have tracks and be at/near 100% acquired
            if track_file_count > 0 and percent_of_tracks >= 99.0:
                ready_count += 1
        
        return ready_count
    except Exception:
        return 0


def get_dashboard_stats(cfg: LidarrConfig) -> Dict[str, Any]:
    """
    Get all dashboard statistics for Lidarr in a single API call.
    Returns: total_artists, artists_with_files, total_tracks, tracks_downloaded
    """
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        total_artists = len(artists)
        artists_with_files = 0
        total_tracks = 0
        tracks_downloaded = 0
        
        for artist in artists:
            stats = artist.get("statistics", {})
            if isinstance(stats, dict):
                # Artists with files
                albums_on_disk = stats.get("albumCount", 0)
                if albums_on_disk > 0:
                    artists_with_files += 1
                
                # Total tracks
                total_tracks += stats.get("trackCount", 0)
                
                # Tracks downloaded (only from artists with files)
                if albums_on_disk > 0:
                    tracks_downloaded += stats.get("trackFileCount", 0)
        
        return {
            "total": total_artists,
            "with_files": artists_with_files,
            "total_tracks": total_tracks,
            "tracks_downloaded": tracks_downloaded,
        }
    except Exception:
        return {
            "total": 0,
            "with_files": 0,
            "total_tracks": 0,
            "tracks_downloaded": 0,
        }


def get_total_library_count(cfg: LidarrConfig) -> int:
    """Get total count of Lidarr artists in the library."""
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        return len(artists)
    except Exception:
        return 0


def get_total_with_files_count(cfg: LidarrConfig) -> int:
    """Get count of Lidarr artists that have files (albums)."""
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        with_files_count = 0
        for artist in artists:
            # Check if artist has files on disk by checking statistics
            stats = artist.get("statistics", {})
            if isinstance(stats, dict):
                # Check if there are albums on disk
                albums_on_disk = stats.get("albumCount", 0)
                if albums_on_disk > 0:
                    with_files_count += 1
            elif artist.get("sizeOnDisk", 0) > 0:
                # Alternative: check total size on disk
                with_files_count += 1
        
        return with_files_count
    except Exception:
        return 0


def get_total_tracks_count(cfg: LidarrConfig) -> int:
    """Get total count of tracks across all Lidarr artists."""
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        total_tracks = 0
        for artist in artists:
            # Sum up tracks from statistics
            stats = artist.get("statistics", {})
            if isinstance(stats, dict):
                total_tracks += stats.get("trackCount", 0)
        
        return total_tracks
    except Exception:
        return 0


def get_total_tracks_downloaded_count(cfg: LidarrConfig) -> int:
    """Get total count of downloaded tracks across all Lidarr artists."""
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        total_downloaded_tracks = 0
        for artist in artists:
            # Sum up tracks that have been downloaded (artist has files)
            stats = artist.get("statistics", {})
            if isinstance(stats, dict):
                # Only count tracks from artists that have files on disk
                albums_on_disk = stats.get("albumCount", 0)
                if albums_on_disk > 0:
                    total_downloaded_tracks += stats.get("trackFileCount", 0)
        
        return total_downloaded_tracks
    except Exception:
        return 0
