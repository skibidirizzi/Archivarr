"""Shared application configuration models.

This module intentionally stays service-agnostic so individual *arr clients
(lidarr/sonarr/radarr) don't need to define or depend on other services' config.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class LidarrServiceConfig:
    url: str
    api_key: str
    archive_root: Optional[Path]
    missing_page_size: int
    missing_max_pages: int
    enabled: bool = True


@dataclass
class SonarrServiceConfig:
    url: Optional[str]
    api_key: Optional[str]
    archive_root: Optional[Path]
    enabled: bool = True


@dataclass
class RadarrServiceConfig:
    url: Optional[str]
    api_key: Optional[str]
    archive_root: Optional[Path]
    enabled: bool = True


@dataclass
class AppConfig:
    """Application configuration loaded from config.ini."""

    lidarr: LidarrServiceConfig
    sonarr: SonarrServiceConfig
    radarr: RadarrServiceConfig

    # Shared HTTP/runtime settings
    verify_ssl: bool
    timeout_sec: int
    sleep_between_items: float
    limit_items: int
    verbose_log: bool
