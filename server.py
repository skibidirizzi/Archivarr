from __future__ import annotations

import configparser
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app_config import AppConfig, LidarrServiceConfig, SonarrServiceConfig, RadarrServiceConfig
from lidarr_client import (
    lidarr_session,
    lidarr_get,
    lidarr_post,
    lidarr_put,
    lidarr_pause,
    lidarr_resume,
    health_check as lidarr_health_check,
    get_ready_to_archive_count as lidarr_get_ready_count,
    get_dashboard_stats as lidarr_get_dashboard_stats,
)
from sonarr_client import (
    SonarrConfig,
    sonarr_session,
    sonarr_get,
    sonarr_post,
    sonarr_put,
    health_check as sonarr_health_check,
    get_ready_to_archive_count as sonarr_get_ready_count,
    get_dashboard_stats as sonarr_get_dashboard_stats,
)
from radarr_client import (
    RadarrConfig,
    radarr_session,
    radarr_get,
    radarr_post,
    radarr_put,
    health_check as radarr_health_check,
    get_ready_to_archive_count as radarr_get_ready_count,
    get_dashboard_stats as radarr_get_dashboard_stats,
)
from storage import load_json_file, save_json_file, load_ini, save_ini
from logger import create_logger, save_logs_to_file


# ------------------------------------------------------------------------------
# App + Paths
# ------------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("ARCHIVARR_CONFIG", APP_DIR / "config.ini"))
DATA_DIR = APP_DIR / "data"
LAST_SCAN_FILE = DATA_DIR / "last_scan.json"
ACTIVITY_FILE = DATA_DIR / "activity.json"

app = FastAPI(title="Archivarr")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ACTIVITY: Dict[str, Dict[str, Any]] = {}
LAST_SCAN: Optional[Dict[str, Any]] = None
LOGS_DIR = APP_DIR / "logs"

# Ensure logs directory exists at startup
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"Warning: Failed to create logs directory: {e}")


# ------------------------------------------------------------------------------
# Data Persistence Helpers
# ------------------------------------------------------------------------------

def _norm_url(url: str) -> str:
    return (url or "").rstrip("/")


def _is_service_configured(url: Optional[str], api_key: Optional[str]) -> bool:
    return bool((url or "").strip() and (api_key or "").strip())


def persist_last_scan(scan_result: Dict[str, Any]) -> None:
    """Save last scan results to disk."""
    save_json_file(LAST_SCAN_FILE, scan_result)


def persist_activity() -> None:
    """Save scan/move activity tracking data to disk."""
    save_json_file(ACTIVITY_FILE, ACTIVITY)


LAST_SCAN = load_json_file(LAST_SCAN_FILE)
ACTIVITY = load_json_file(ACTIVITY_FILE) or {}

# ------------------------------------------------------------------------------
# UI Wiring Models
# ------------------------------------------------------------------------------

class LidarrConnection(BaseModel):
    base_url: str
    api_key: str


class SonarrConnection(BaseModel):
    base_url: str
    api_key: str


class RadarrConnection(BaseModel):
    base_url: str
    api_key: str


# ------------------------------------------------------------------------------
# Configuration Management
# ------------------------------------------------------------------------------

def load_app_config() -> Optional[AppConfig]:
    """Load config if it exists, return None if not configured yet."""
    cp = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        return None
    cp.read(CONFIG_PATH, encoding="utf-8")

    # Services are optional. If a service is configured (url + api_key), its archive root is required.
    lidarr_url = _norm_url(cp.get("Lidarr", "url", fallback="").strip())
    lidarr_api_key = cp.get("Lidarr", "api_key", fallback="").strip()
    sonarr_url = _norm_url(cp.get("Sonarr", "url", fallback="").strip()) or None
    sonarr_api_key = cp.get("Sonarr", "api_key", fallback="").strip() or None
    radarr_url = _norm_url(cp.get("Radarr", "url", fallback="").strip()) or None
    radarr_api_key = cp.get("Radarr", "api_key", fallback="").strip() or None

    lidarr_archive_raw = cp.get("Archive", "lidarr_archive_root", fallback="").strip()
    lidarr_archive_root = Path(lidarr_archive_raw) if lidarr_archive_raw else None
    sonarr_archive_raw = cp.get("Archive", "sonarr_archive_root", fallback="").strip()
    sonarr_archive_root = Path(sonarr_archive_raw) if sonarr_archive_raw else None
    radarr_archive_raw = cp.get("Archive", "radarr_archive_root", fallback="").strip()
    radarr_archive_root = Path(radarr_archive_raw) if radarr_archive_raw else None

    # Shared HTTP settings live under [Runtime]. For backwards compatibility,
    # we also fall back to legacy per-service keys if present.
    verify_ssl = cp.getboolean(
        "Runtime",
        "verify_ssl",
        fallback=cp.getboolean("Lidarr", "verify_ssl", fallback=True),
    )
    timeout_sec = cp.getint(
        "Runtime",
        "timeout_sec",
        fallback=cp.getint("Lidarr", "timeout_sec", fallback=30),
    )

    cfg = AppConfig(
        lidarr=LidarrServiceConfig(
            url=lidarr_url,
            api_key=lidarr_api_key,
            archive_root=lidarr_archive_root,
            missing_page_size=cp.getint("Runtime", "missing_page_size", fallback=2000),
            missing_max_pages=cp.getint("Runtime", "missing_max_pages", fallback=50),
            enabled=cp.getboolean("Lidarr", "enabled", fallback=True),
        ),
        sonarr=SonarrServiceConfig(
            url=sonarr_url,
            api_key=sonarr_api_key,
            archive_root=sonarr_archive_root,
            enabled=cp.getboolean("Sonarr", "enabled", fallback=True),
        ),
        radarr=RadarrServiceConfig(
            url=radarr_url,
            api_key=radarr_api_key,
            archive_root=radarr_archive_root,
            enabled=cp.getboolean("Radarr", "enabled", fallback=True),
        ),
        verify_ssl=verify_ssl,
        timeout_sec=timeout_sec,
        sleep_between_items=cp.getfloat("Runtime", "sleep_between_items", fallback=0.0),
        limit_items=cp.getint("Runtime", "limit_items", fallback=0),
        verbose_log=cp.getboolean("Runtime", "verbose_log", fallback=False),
    )
    
    if _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key):
        if cfg.lidarr.archive_root is None:
            raise ValueError("config.ini: [Archive] lidarr_archive_root is required when Lidarr is configured")
        if not cfg.lidarr.archive_root.exists():
            raise ValueError(f"config.ini: [Archive] lidarr_archive_root does not exist: {cfg.lidarr.archive_root}")
        if not cfg.lidarr.archive_root.is_dir():
            raise ValueError(f"config.ini: [Archive] lidarr_archive_root is not a directory: {cfg.lidarr.archive_root}")

    if _is_service_configured(cfg.sonarr.url, cfg.sonarr.api_key):
        if cfg.sonarr.archive_root is None:
            raise ValueError("config.ini: [Archive] sonarr_archive_root is required when Sonarr is configured")
        if not cfg.sonarr.archive_root.exists():
            raise ValueError(f"config.ini: [Archive] sonarr_archive_root does not exist: {cfg.sonarr.archive_root}")
        if not cfg.sonarr.archive_root.is_dir():
            raise ValueError(f"config.ini: [Archive] sonarr_archive_root is not a directory: {cfg.sonarr.archive_root}")

    if _is_service_configured(cfg.radarr.url, cfg.radarr.api_key):
        if cfg.radarr.archive_root is None:
            raise ValueError("config.ini: [Archive] radarr_archive_root is required when Radarr is configured")
        if not cfg.radarr.archive_root.exists():
            raise ValueError(f"config.ini: [Archive] radarr_archive_root does not exist: {cfg.radarr.archive_root}")
        if not cfg.radarr.archive_root.is_dir():
            raise ValueError(f"config.ini: [Archive] radarr_archive_root is not a directory: {cfg.radarr.archive_root}")

    return cfg


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------

@app.get("/api/v1/connections/lidarr")
def api_get_lidarr_connection():
    cp = load_ini(CONFIG_PATH)
    base_url = cp.get("Lidarr", "url", fallback="")
    api_key = cp.get("Lidarr", "api_key", fallback="")
    return {"base_url": base_url, "api_key": api_key}


@app.put("/api/v1/connections/lidarr")
def api_save_lidarr_connection(conn: LidarrConnection):
    cp = load_ini(CONFIG_PATH)
    if "Lidarr" not in cp:
        cp["Lidarr"] = {}

    cp["Lidarr"]["url"] = _norm_url(conn.base_url.strip())
    cp["Lidarr"]["api_key"] = conn.api_key.strip()

    # Seed shared defaults under [Runtime] (service-agnostic)
    if "Runtime" not in cp:
        cp["Runtime"] = {}
    if "verify_ssl" not in cp["Runtime"]:
        cp["Runtime"]["verify_ssl"] = "true"
    if "timeout_sec" not in cp["Runtime"]:
        cp["Runtime"]["timeout_sec"] = "30"

    save_ini(CONFIG_PATH, cp)
    return {"ok": True}


async def _ping_default_service(request: Request, port: int) -> Dict[str, str]:
    host = request.url.hostname or "localhost"
    scheme = request.url.scheme or "http"

    base_url = f"{scheme}://{host}:{port}"

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            r = await client.get(base_url)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail=f"Could not reach service on {base_url}")

    # Treat any response as evidence the web UI is reachable.
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"Service at {base_url} responded with HTTP {r.status_code}")

    return {
        "base_url": base_url,
        "settings_url": f"{base_url}/settings/general",
    }


@app.get("/api/v1/connections/lidarr/ping-default")
async def api_ping_lidarr_default(request: Request):
    data = await _ping_default_service(request, port=8686)
    return {"ok": True, "pong": True, **data}


@app.post("/api/v1/connections/lidarr/test")
async def api_test_lidarr_connection(conn: LidarrConnection):
    base_url = _norm_url(conn.base_url.strip())
    api_key = conn.api_key.strip()

    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is required")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    url = f"{base_url}/api/v1/system/status"
    headers = {"X-Api-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach Lidarr")

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized (bad API key)")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=f"Lidarr error: {r.text[:200]}")

    if not r.content:
        raise HTTPException(status_code=502, detail="Lidarr returned an empty response")

    try:
        lidarr_status = r.json()
    except ValueError:
        content_type = r.headers.get("content-type", "")
        snippet = (r.text or "")[:200]
        raise HTTPException(
            status_code=502,
            detail=(
                "Lidarr returned non-JSON data "
                f"(status {r.status_code}, content-type {content_type}): {snippet}"
            ),
        )
    return {"ok": True, "status": {"version": lidarr_status.get("version", "unknown")}}


@app.post("/api/v1/connections/sonarr/test")
async def api_test_sonarr_connection(conn: SonarrConnection):
    base_url = _norm_url(conn.base_url.strip())
    api_key = conn.api_key.strip()

    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is required")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    url = f"{base_url}/api/v3/system/status"
    headers = {"X-Api-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach Sonarr")

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized (bad API key)")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=f"Sonarr error: {r.text[:200]}")

    if not r.content:
        raise HTTPException(status_code=502, detail="Sonarr returned an empty response")

    try:
        sonarr_status = r.json()
    except ValueError:
        content_type = r.headers.get("content-type", "")
        snippet = (r.text or "")[:200]
        raise HTTPException(
            status_code=502,
            detail=(
                "Sonarr returned non-JSON data "
                f"(status {r.status_code}, content-type {content_type}): {snippet}"
            ),
        )
    return {"ok": True, "status": {"version": sonarr_status.get("version", "unknown")}}


@app.get("/api/v1/connections/sonarr/ping-default")
async def api_ping_sonarr_default(request: Request):
    data = await _ping_default_service(request, port=8989)
    return {"ok": True, "pong": True, **data}


@app.post("/api/v1/connections/radarr/test")
async def api_test_radarr_connection(conn: RadarrConnection):
    base_url = _norm_url(conn.base_url.strip())
    api_key = conn.api_key.strip()

    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is required")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    url = f"{base_url}/api/v3/system/status"
    headers = {"X-Api-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach Radarr")

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized (bad API key)")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=f"Radarr error: {r.text[:200]}")

    if not r.content:
        raise HTTPException(status_code=502, detail="Radarr returned an empty response")

    try:
        radarr_status = r.json()
    except ValueError:
        content_type = r.headers.get("content-type", "")
        snippet = (r.text or "")[:200]
        raise HTTPException(
            status_code=502,
            detail=(
                "Radarr returned non-JSON data "
                f"(status {r.status_code}, content-type {content_type}): {snippet}"
            ),
        )
    return {"ok": True, "status": {"version": radarr_status.get("version", "unknown")}}


@app.get("/api/v1/connections/radarr/ping-default")
async def api_ping_radarr_default(request: Request):
    data = await _ping_default_service(request, port=7878)
    return {"ok": True, "pong": True, **data}


@app.get("/api/v1/status")
def api_status():
    # UI chips endpoint - returns independent health status for each service
    try:
        cfg = load_app_config()
        if cfg is None:
            return {
                "configured": False,
                "lidarr": {"ok": False, "connected": False, "error": "Not configured"},
                "sonarr": {"ok": False, "connected": False, "error": "Not configured"},
                "radarr": {"ok": False, "connected": False, "error": "Not configured"},
                "scheduler": {"enabled": False},
                "lastActivity": None,
            }

        lidarr_h = {"ok": False, "connected": False, "error": "Not configured"}
        if _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key):
            if not cfg.lidarr.enabled:
                lidarr_h = {"ok": False, "connected": False, "disabled": True, "url": cfg.lidarr.url}
            else:
                lidarr_h = lidarr_health_check(cfg)
                lidarr_h["url"] = cfg.lidarr.url

        last_activity_ts = None
        if ACTIVITY:
            last_activity_ts = max(r["created"] for r in ACTIVITY.values())

        # Check Sonarr and Radarr health independently
        cp = configparser.ConfigParser()
        cp.read(CONFIG_PATH, encoding="utf-8")
        
        sonarr_h = {"ok": False, "connected": False, "error": "Not configured"}
        radarr_h = {"ok": False, "connected": False, "error": "Not configured"}
        
        try:
            sonarr_url = cp.get("Sonarr", "url", fallback="").strip()
            sonarr_key = cp.get("Sonarr", "api_key", fallback="").strip()
            if sonarr_url and sonarr_key:
                if not cfg.sonarr.enabled:
                    sonarr_h = {"ok": False, "connected": False, "disabled": True, "url": sonarr_url}
                else:
                    archive = cfg.sonarr.archive_root if cfg else None
                    sonarr_cfg = SonarrConfig(sonarr_url, sonarr_key, archive_root=archive)
                    sonarr_h = sonarr_health_check(sonarr_cfg)
                    sonarr_h["url"] = sonarr_url  # Add URL to response
        except Exception as e:
            sonarr_h = {"ok": False, "connected": False, "error": str(e)}
        
        try:
            radarr_url = cp.get("Radarr", "url", fallback="").strip()
            radarr_key = cp.get("Radarr", "api_key", fallback="").strip()
            if radarr_url and radarr_key:
                if not cfg.radarr.enabled:
                    radarr_h = {"ok": False, "connected": False, "disabled": True, "url": radarr_url}
                else:
                    archive = cfg.radarr.archive_root if cfg else None
                    radarr_cfg = RadarrConfig(radarr_url, radarr_key, archive_root=archive)
                    radarr_h = radarr_health_check(radarr_cfg)
                    radarr_h["url"] = radarr_url  # Add URL to response
        except Exception as e:
            radarr_h = {"ok": False, "connected": False, "error": str(e)}

        return {
            "configured": True,
            "lidarr": lidarr_h,
            "sonarr": sonarr_h,
            "radarr": radarr_h,
            "scheduler": {"enabled": False},
            "lastActivity": last_activity_ts,
        }
    except Exception as e:
        return {
            "configured": False,
            "lidarr": {"ok": False, "error": str(e)},
            "sonarr": {"ok": False, "error": str(e)},
            "radarr": {"ok": False, "error": str(e)},
            "scheduler": {"enabled": False},
            "lastActivity": None,
        }


# ------------------------------------------------------------------------------
# Setup endpoints
# ------------------------------------------------------------------------------

@app.get("/api/v1/setup/status")
def api_setup_status():
    """Check if the app is configured."""
    return {"configured": CONFIG_PATH.exists()}


class SetupConfig(BaseModel):
    lidarr_url: str = ""
    lidarr_api_key: str = ""
    lidarr_archive_root: str = ""

    sonarr_url: str = ""
    sonarr_api_key: str = ""
    sonarr_archive_root: str = ""

    radarr_url: str = ""
    radarr_api_key: str = ""
    radarr_archive_root: str = ""
    verify_ssl: bool = True
    timeout_sec: int = 30

    # Runtime knobs (service-agnostic).
    sleep_between_items: float = 0.0
    limit_items: int = 0

    verbose_log: bool = False
    missing_page_size: int = 2000
    missing_max_pages: int = 50

    # If true, the server will create missing archive root directories during setup.
    create_missing_dirs: bool = False



@app.post("/api/v1/setup/configure")
def api_setup_configure(setup: SetupConfig):
    """Save initial configuration."""
    try:
        cp = configparser.ConfigParser()

        # Create all sections with defaults
        cp["Server"] = {
            "port": "8787",
            "bind": "127.0.0.1",
        }

        lidarr_url = _norm_url(setup.lidarr_url.strip())
        lidarr_key = setup.lidarr_api_key.strip()
        sonarr_url = _norm_url(setup.sonarr_url.strip())
        sonarr_key = setup.sonarr_api_key.strip()
        radarr_url = _norm_url(setup.radarr_url.strip())
        radarr_key = setup.radarr_api_key.strip()

        # Validate archive roots before writing config.
        # If a root doesn't exist, return an actionable response so the UI can
        # offer to create it or let the user choose a different folder.
        service_requirements: List[Tuple[str, str, bool]] = [
            ("lidarr", setup.lidarr_archive_root.strip(), bool(lidarr_url and lidarr_key)),
            ("sonarr", setup.sonarr_archive_root.strip(), bool(sonarr_url and sonarr_key)),
            ("radarr", setup.radarr_archive_root.strip(), bool(radarr_url and radarr_key)),
        ]

        for service, archive_root, configured in service_requirements:
            if not configured:
                continue

            if not archive_root:
                return {"ok": False, "error": f"{service.title()} archive root path is required"}

            root_path = Path(archive_root)
            if root_path.exists():
                if not root_path.is_dir():
                    return {"ok": False, "error": f"{service.title()} archive root is not a directory: {archive_root}"}
                continue

            if setup.create_missing_dirs:
                try:
                    root_path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    return {"ok": False, "error": f"Could not create {service.title()} archive root: {archive_root} ({e})"}
            else:
                return {
                    "ok": False,
                    "needsAction": "create_or_select",
                    "service": service,
                    "path": archive_root,
                    "message": f"{service.title()} archive root does not exist: {archive_root}",
                }

        if lidarr_url or lidarr_key:
            cp["Lidarr"] = {
                "url": lidarr_url,
                "api_key": lidarr_key,
            }

        if sonarr_url or sonarr_key:
            cp["Sonarr"] = {
                "url": sonarr_url,
                "api_key": sonarr_key,
            }

        if radarr_url or radarr_key:
            cp["Radarr"] = {
                "url": radarr_url,
                "api_key": radarr_key,
            }

        sleep_between_items = float(setup.sleep_between_items or 0.0)
        limit_items = int(setup.limit_items or 0)

        if "Archive" not in cp:
            cp["Archive"] = {}

        if setup.lidarr_archive_root.strip():
            cp["Archive"]["lidarr_archive_root"] = setup.lidarr_archive_root.strip()
        if setup.sonarr_archive_root.strip():
            cp["Archive"]["sonarr_archive_root"] = setup.sonarr_archive_root.strip()
        if setup.radarr_archive_root.strip():
            cp["Archive"]["radarr_archive_root"] = setup.radarr_archive_root.strip()

        cp["Runtime"] = {
            # Preferred generic keys
            "sleep_between_items": str(sleep_between_items),
            "limit_items": str(limit_items),
            "verify_ssl": "true" if setup.verify_ssl else "false",
            "timeout_sec": str(setup.timeout_sec),
            "verbose_log": "true" if setup.verbose_log else "false",
            "missing_page_size": str(setup.missing_page_size),
            "missing_max_pages": str(setup.missing_max_pages),
        }

        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Write config file using storage module
        save_ini(CONFIG_PATH, cp)

        return {"ok": True, "message": "Configuration saved successfully"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------------------------
# Missing/Wanted Album Fetching
# ------------------------------------------------------------------------------

def _extract_int(*candidates: Any) -> Optional[int]:
    for c in candidates:
        try:
            if c is None:
                continue
            if isinstance(c, bool):
                continue
            if isinstance(c, int):
                return c
            if isinstance(c, str) and c.strip().isdigit():
                return int(c.strip())
        except Exception:
            continue
    return None


def fetch_missing_album_ids(cfg: AppConfig, s: requests.Session) -> Set[int]:
    missing_album_ids: Set[int] = set()

    page_size = max(1, int(cfg.lidarr.missing_page_size or 2000))
    max_pages = max(1, int(cfg.lidarr.missing_max_pages or 50))

    def extract_records(data: Any) -> List[dict]:
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return data["records"]
        if isinstance(data, list):
            return data
        return []

    def add_record_ids(records: List[dict]) -> None:
        for rec in records:
            if not isinstance(rec, dict):
                continue
            album_id = _extract_int(
                rec.get("albumId"),
                (rec.get("album") or {}).get("id") if isinstance(rec.get("album"), dict) else None,
                (rec.get("album") or {}).get("albumId") if isinstance(rec.get("album"), dict) else None,
            )
            if album_id is not None:
                missing_album_ids.add(int(album_id))

    try:
        for page in range(1, max_pages + 1):
            data = lidarr_get(
                cfg,
                s,
                "/api/v1/wanted/missing",
                params={"page": page, "pageSize": page_size},
            )
            records = extract_records(data)
            if not records:
                break

            add_record_ids(records)

            if isinstance(data, dict) and isinstance(data.get("totalRecords"), int):
                total = int(data["totalRecords"])
                if page * page_size >= total:
                    break

        return missing_album_ids

    except requests.HTTPError:
        data = lidarr_get(cfg, s, "/api/v1/wanted/missing")
        records = extract_records(data)
        add_record_ids(records)
        return missing_album_ids


# ------------------------------------------------------------------------------
# Quality Profile & Cutoff Evaluation
# ------------------------------------------------------------------------------

def flatten_quality_profile(items: List[dict]) -> Tuple[List[Tuple[int, str]], Dict[int, List[int]], Dict[int, str]]:
    qualities_ordered: List[Tuple[int, str]] = []
    group_members: Dict[int, List[int]] = {}
    group_names: Dict[int, str] = {}

    def extract_leaf_quality(node: dict) -> Optional[Tuple[int, str]]:
        q = node.get("quality")
        if not isinstance(q, dict):
            return None

        qid = q.get("id")
        if isinstance(qid, int) or (isinstance(qid, str) and qid.isdigit()):
            return (int(qid), str(q.get("name") or ""))

        q2 = q.get("quality")
        if isinstance(q2, dict):
            qid2 = q2.get("id")
            if isinstance(qid2, int) or (isinstance(qid2, str) and str(qid2).isdigit()):
                return (int(qid2), str(q2.get("name") or ""))
        return None

    for node in items or []:
        if "quality" not in node and isinstance(node.get("items"), list) and node.get("id") is not None:
            gid = int(node.get("id"))
            gname = str(node.get("name") or f"group:{gid}")
            group_names[gid] = gname
            group_members.setdefault(gid, [])

            for child in node.get("items") or []:
                got = extract_leaf_quality(child)
                if got:
                    qid, qname = got
                    qualities_ordered.append((qid, qname))
                    group_members[gid].append(qid)
            continue

        got = extract_leaf_quality(node)
        if got:
            qualities_ordered.append(got)

    seen = set()
    dedup: List[Tuple[int, str]] = []
    for qid, qname in qualities_ordered:
        if qid in seen:
            continue
        seen.add(qid)
        dedup.append((qid, qname))
    qualities_ordered = dedup

    for gid, mem in list(group_members.items()):
        seen2 = set()
        out = []
        for qid in mem:
            if qid in seen2:
                continue
            seen2.add(qid)
            out.append(qid)
        group_members[gid] = out

    return qualities_ordered, group_members, group_names


def autodetect_better_direction(ordered_qualities: List[Tuple[int, str]]) -> bool:
    if not ordered_qualities:
        return True

    def score(name: str) -> int:
        n = name.lower()
        s = 0
        if "flac" in n: s += 50
        if "wavpack" in n: s += 45
        if "ape" in n: s += 44
        if "alac" in n: s += 43
        if "24" in n: s += 10
        if "320" in n: s += 20
        if "256" in n: s += 15
        if "192" in n: s += 10
        if "128" in n: s += 5
        return s

    first = score(ordered_qualities[0][1])
    last = score(ordered_qualities[-1][1])
    return first >= last


def build_quality_rank_map(ordered_qualities: List[Tuple[int, str]], better_is_lower_index: bool) -> Dict[int, int]:
    n = len(ordered_qualities)
    rank: Dict[int, int] = {}
    for idx, (qid, _) in enumerate(ordered_qualities):
        rank[qid] = (n - idx) if better_is_lower_index else (idx + 1)
    return rank


def build_group_rank_map(group_members: Dict[int, List[int]], quality_rank: Dict[int, int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for gid, members in group_members.items():
        ranks = [quality_rank[qid] for qid in members if qid in quality_rank]
        if not ranks:
            continue
        out[gid] = min(ranks)
    return out


def percent_complete(stats: dict) -> float:
    try:
        return float(stats.get("percentOfTracks") or 0.0)
    except Exception:
        return 0.0


def _extract_cutoff_id(profile: dict) -> int:
    cutoff_raw = profile.get("cutoff")

    if isinstance(cutoff_raw, dict):
        if "id" in cutoff_raw:
            try:
                return int(cutoff_raw.get("id") or 0)
            except Exception:
                return 0
        q = cutoff_raw.get("quality")
        if isinstance(q, dict) and "id" in q:
            try:
                return int(q.get("id") or 0)
            except Exception:
                return 0
        return 0

    try:
        return int(cutoff_raw or 0)
    except Exception:
        return 0


def evaluate_album_cutoff(
    album: dict,
    trackfiles: List[dict],
    rank_map: Dict[int, int],
    cutoff_rank: int,
    cutoff_id: int,
    cutoff_label: str,
    cutoff_format_score: int,
    enforce_format_score: bool,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    stats = album.get("statistics") or {}

    pct = percent_complete(stats)
    if pct < 99.999:
        reasons.append(f"Not complete: percentOfTracks={pct:.3f}")
        return False, reasons

    tf_count = int(stats.get("trackFileCount") or 0)
    if tf_count <= 0:
        reasons.append("No track files (trackFileCount=0)")
        return False, reasons

    if not trackfiles:
        reasons.append("No trackfiles returned from /trackfile for this album")
        return False, reasons

    for tf in trackfiles:
        qwrap = (tf.get("quality") or {})
        q = (qwrap.get("quality") or {}) if isinstance(qwrap, dict) else {}
        qid = q.get("id")
        qname = q.get("name") or str(qid)

        if qid is None:
            reasons.append("Trackfile missing quality id")
            return False, reasons

        tf_rank = rank_map.get(int(qid))
        if tf_rank is None:
            reasons.append(f"Trackfile quality id {qid} not found in rank map")
            return False, reasons

        if tf_rank < cutoff_rank:
            reasons.append(
                f"Below cutoff: file quality={qname} (id={qid}) < cutoff {cutoff_label} (id={cutoff_id})"
            )
            return False, reasons

        if enforce_format_score and int(cutoff_format_score or 0) > 0:
            cfs = qwrap.get("customFormatScore") if isinstance(qwrap, dict) else 0
            cfs = 0 if cfs is None else cfs
            try:
                if int(cfs) < int(cutoff_format_score):
                    reasons.append(f"CustomFormatScore below cutoff: have={cfs} need={cutoff_format_score}")
                    return False, reasons
            except Exception:
                reasons.append("CustomFormatScore missing/unreadable")
                return False, reasons

    return True, []


# ------------------------------------------------------------------------------
# Archive Root & Folder Management
# ------------------------------------------------------------------------------

def ensure_lidarr_root_folder(cfg: AppConfig, s: requests.Session) -> None:
    # Ensure the path exists on disk before asking Lidarr to add it; Lidarr returns 400 otherwise.
    if not cfg.lidarr.archive_root:
        raise ValueError("Lidarr archive root is not configured")
    root_path = Path(cfg.lidarr.archive_root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)

    roots = lidarr_get(cfg, s, "/api/v1/rootfolder")
    target = str(root_path).rstrip("\\/").lower()
    for r in roots:
        p = (r.get("path") or "").rstrip("\\/").lower()
        if p == target:
            return
    # Lidarr requires name, defaultQualityProfileId, defaultMetadataProfileId
    quality_profiles = lidarr_get(cfg, s, "/api/v1/qualityprofile")
    metadata_profiles = lidarr_get(cfg, s, "/api/v1/metadataprofile")
    if not quality_profiles:
        raise ValueError("No Lidarr quality profiles found; cannot create root folder")
    if not metadata_profiles:
        raise ValueError("No Lidarr metadata profiles found; cannot create root folder")

    payload = {
        "id": 0,
        "path": str(root_path),
        "name": Path(root_path).name or str(root_path),
        "defaultQualityProfileId": int(quality_profiles[0].get("id", 0)),
        "defaultMetadataProfileId": int(metadata_profiles[0].get("id", 0)),
    }
    lidarr_post(cfg, s, "/api/v1/rootfolder", payload)


# Back-compat alias: this helper was originally named generically but is Lidarr-specific.



def ensure_sonarr_root_folder(cfg: SonarrConfig, s: requests.Session) -> None:
    if not cfg.archive_root:
        raise ValueError("Sonarr archive root is not configured")
    root_path = Path(cfg.archive_root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)

    roots = sonarr_get(cfg, s, "/api/v3/rootfolder")
    target = str(root_path).rstrip("\\/").lower()
    for r in roots:
        p = (r.get("path") or "").rstrip("\\/").lower()
        if p == target:
            return

    sonarr_post(cfg, s, "/api/v3/rootfolder", {"path": str(root_path)})


def ensure_radarr_root_folder(cfg: RadarrConfig, s: requests.Session) -> None:
    if not cfg.archive_root:
        raise ValueError("Radarr archive root is not configured")
    root_path = Path(cfg.archive_root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)

    roots = radarr_get(cfg, s, "/api/v3/rootfolder")
    target = str(root_path).rstrip("\\/").lower()
    for r in roots:
        p = (r.get("path") or "").rstrip("\\/").lower()
        if p == target:
            return

    radarr_post(cfg, s, "/api/v3/rootfolder", {"path": str(root_path)})


# ------------------------------------------------------------------------------
# Archive Scanning & Execution
# ------------------------------------------------------------------------------

def scan(cfg: AppConfig) -> Dict[str, Any]:
    """
    Scan all configured services (Lidarr, Sonarr, Radarr) for eligible items to archive.
    Returns items grouped by service type.
    """
    eligible: List[dict] = []
    ineligible: List[dict] = []

    # Runtime knobs are historically named for Lidarr, but should apply across
    # all configured services.
    max_items_per_service = int(cfg.limit_items or 0)

    # Scan Lidarr
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        if max_items_per_service > 0:
            artists = artists[: max_items_per_service]

        # Normalize archive root for comparison
        if not cfg.lidarr.archive_root:
            raise ValueError("Lidarr archive root not configured")
        archive_root_lower = str(cfg.lidarr.archive_root).rstrip("\\/").lower()

        for artist in artists:
            artist_id = int(artist["id"])
            name = artist.get("artistName") or f"artist:{artist_id}"
            artist_path = artist.get("path") or ""

            # Skip unmonitored artists
            if not artist.get("monitored", True):
                ineligible.append({
                    "service": "lidarr",
                    "itemId": artist_id,
                    "itemName": name,
                    "path": artist_path,
                    "reasons": ["Artist not monitored"],
                })
                continue

            # Skip artists already in archive root
            artist_path_lower = artist_path.rstrip("\\/").lower()
            if artist_path_lower.startswith(archive_root_lower):
                ineligible.append({
                    "service": "lidarr",
                    "itemId": artist_id,
                    "itemName": name,
                    "path": artist_path,
                    "reasons": ["Already in archive root"],
                })
                continue

            # Check statistics to determine eligibility
            stats = artist.get("statistics", {})
            if not isinstance(stats, dict):
                ineligible.append({
                    "service": "lidarr",
                    "itemId": artist_id,
                    "itemName": name,
                    "path": artist_path,
                    "reasons": ["No statistics available"],
                })
                continue

            # Check if artist has tracks on disk
            track_file_count = stats.get("trackFileCount", 0)
            total_track_count = stats.get("totalTrackCount", 0)
            percent_of_tracks = stats.get("percentOfTracks", 0)
            
            # Artist is ineligible if no tracks downloaded
            if track_file_count == 0:
                ineligible.append({
                    "service": "lidarr",
                    "itemId": artist_id,
                    "itemName": name,
                    "path": artist_path,
                    "reasons": ["No tracks downloaded yet"],
                })
                continue

            # Check if all desired tracks have been acquired (cutoff met)
            # percentOfTracks is close to 100 when all tracks are downloaded
            if percent_of_tracks < 99.0:  # Allow 99% to account for rounding
                ineligible.append({
                    "service": "lidarr",
                    "itemId": artist_id,
                    "itemName": name,
                    "path": artist_path,
                    "reasons": [f"Not all desired tracks acquired ({percent_of_tracks:.1f}%)"],
                })
                continue

            # Artist is eligible for archiving
            eligible.append({
                "service": "lidarr",
                "itemId": artist_id,
                "itemName": name,
                "path": artist_path,
            })
    except Exception as e:
        # Lidarr scan failed, but continue with other services
        pass

    # Scan Sonarr if configured
    if cfg.sonarr.url and cfg.sonarr.api_key:
        try:
            sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
            series_list = sonarr_get(sonarr_cfg, sonarr_session(sonarr_cfg), "/api/v3/series")

            if max_items_per_service > 0:
                series_list = series_list[: max_items_per_service]
            
            # Use Sonarr-specific archive root
            if not cfg.sonarr.archive_root:
                raise ValueError("Sonarr archive root not configured")
            archive_root_lower = str(cfg.sonarr.archive_root).rstrip("\\/").lower()
            
            for series in series_list:
                series_id = int(series["id"])
                name = series.get("title") or f"series:{series_id}"
                series_path = series.get("path") or ""

                # Skip unmonitored series
                if not series.get("monitored", True):
                    ineligible.append({
                        "service": "sonarr",
                        "itemId": series_id,
                        "itemName": name,
                        "path": series_path,
                        "reasons": ["Series not monitored"],
                    })
                    continue

                # Skip series already in archive root
                series_path_lower = series_path.rstrip("\\/").lower()
                if series_path_lower.startswith(archive_root_lower):
                    ineligible.append({
                        "service": "sonarr",
                        "itemId": series_id,
                        "itemName": name,
                        "path": series_path,
                        "reasons": ["Already in archive root"],
                    })
                    continue

                # Use statistics to determine eligibility (episodes downloaded vs total)
                stats = series.get("statistics", {})
                if not isinstance(stats, dict):
                    ineligible.append({
                        "service": "sonarr",
                        "itemId": series_id,
                        "itemName": name,
                        "path": series_path,
                        "reasons": ["No statistics available"],
                    })
                    continue

                total_episodes = int(stats.get("episodeCount", 0))
                episodes_with_files = int(stats.get("episodeFileCount", 0))

                if episodes_with_files == 0:
                    ineligible.append({
                        "service": "sonarr",
                        "itemId": series_id,
                        "itemName": name,
                        "path": series_path,
                        "reasons": ["No episodes downloaded yet"],
                    })
                    continue

                # Eligible when nearly all desired episodes have files (allow 99% for rounding)
                pct = (episodes_with_files / total_episodes * 100) if total_episodes > 0 else 0
                if pct < 99.0:
                    ineligible.append({
                        "service": "sonarr",
                        "itemId": series_id,
                        "itemName": name,
                        "path": series_path,
                        "reasons": [f"Not all desired episodes acquired ({pct:.1f}%)"],
                    })
                    continue

                # Series is eligible for archiving
                eligible.append({
                    "service": "sonarr",
                    "itemId": series_id,
                    "itemName": name,
                    "path": series_path,
                })
        except Exception as e:
            # Sonarr scan failed, continue
            pass

    # Scan Radarr if configured
    if cfg.radarr.url and cfg.radarr.api_key:
        try:
            radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
            movies = radarr_get(radarr_cfg, radarr_session(radarr_cfg), "/api/v3/movie")

            if max_items_per_service > 0:
                movies = movies[: max_items_per_service]
            
            # Use Radarr-specific archive root
            if not cfg.radarr.archive_root:
                raise ValueError("Radarr archive root not configured")
            archive_root_lower = str(cfg.radarr.archive_root).rstrip("\\/").lower()
            
            for movie in movies:
                movie_id = int(movie["id"])
                name = movie.get("title") or f"movie:{movie_id}"
                movie_path = movie.get("path") or ""

                # Skip unmonitored movies
                if not movie.get("monitored", True):
                    ineligible.append({
                        "service": "radarr",
                        "itemId": movie_id,
                        "itemName": name,
                        "path": movie_path,
                        "reasons": ["Movie not monitored"],
                    })
                    continue

                # Skip movies already in archive root
                movie_path_lower = movie_path.rstrip("\\/").lower()
                if movie_path_lower.startswith(archive_root_lower):
                    ineligible.append({
                        "service": "radarr",
                        "itemId": movie_id,
                        "itemName": name,
                        "path": movie_path,
                        "reasons": ["Already in archive root"],
                    })
                    continue

                # Check if movie has file and cutoff is met
                has_file = movie.get("hasFile", False)
                # Default cutoff to met when field is missing
                cutoff_met = not movie.get("qualityCutoffNotMet", False)
                
                if not has_file or not cutoff_met:
                    ineligible.append({
                        "service": "radarr",
                        "itemId": movie_id,
                        "itemName": name,
                        "path": movie_path,
                        "reasons": ["Movie missing file or cutoff not met"],
                    })
                    continue

                # Movie is eligible for archiving
                eligible.append({
                    "service": "radarr",
                    "itemId": movie_id,
                    "itemName": name,
                    "path": movie_path,
                })
        except Exception as e:
            # Radarr scan failed, continue
            pass

    return {
        "eligible": eligible,
        "ineligible": ineligible,
        "eligibleCount": len(eligible),
        "ineligibleCount": len(ineligible),
    }


def move_job(cfg: AppConfig, move_id: str) -> None:
    ACTIVITY[move_id]["status"] = "running"
    log: List[str] = ACTIVITY[move_id].setdefault("log", [])

    # Create logger with both in-memory and real-time file logging
    today = time.strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.txt"
    logger = create_logger("Archive", log, log_file)

    sleep_between_items = float(cfg.sleep_between_items or 0.0)

    lidarr_cfg_ok = _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key)
    sonarr_cfg_ok = _is_service_configured(cfg.sonarr.url, cfg.sonarr.api_key)
    radarr_cfg_ok = _is_service_configured(cfg.radarr.url, cfg.radarr.api_key)

    lidarr_s: Optional[requests.Session] = None
    sonarr_s: Optional[requests.Session] = None
    radarr_s: Optional[requests.Session] = None
    sonarr_cfg: Optional[SonarrConfig] = None
    radarr_cfg: Optional[RadarrConfig] = None

    try:
        logger.info("Starting batch move")

        if not (lidarr_cfg_ok or sonarr_cfg_ok or radarr_cfg_ok):
            raise RuntimeError("No services are configured")

        # Prepare per-service sessions/configs and ensure archive roots exist.
        if lidarr_cfg_ok:
            try:
                lidarr_s = lidarr_session(cfg)
                h = lidarr_health_check(cfg)
                if not h.get("ok"):
                    raise RuntimeError(f"Lidarr not reachable: {h.get('error')}")
                ensure_lidarr_root_folder(cfg, lidarr_s)
                logger.info(f"Ensured Lidarr root folder exists: {cfg.lidarr.archive_root}")
            except Exception as e:
                logger.warn(f"Lidarr not ready for batch move: {e}")
                lidarr_s = None

        if sonarr_cfg_ok:
            try:
                if not cfg.sonarr.archive_root:
                    raise RuntimeError("Sonarr archive root is not configured")
                sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
                sonarr_h = sonarr_health_check(sonarr_cfg)
                if not sonarr_h.get("ok"):
                    raise RuntimeError(f"Sonarr not reachable: {sonarr_h.get('error')}")
                sonarr_s = sonarr_session(sonarr_cfg)
                ensure_sonarr_root_folder(sonarr_cfg, sonarr_s)
                logger.info(f"Ensured Sonarr root folder exists: {cfg.sonarr.archive_root}")
            except Exception as e:
                logger.warn(f"Sonarr not ready for batch move: {e}")
                sonarr_s = None
                sonarr_cfg = None

        if radarr_cfg_ok:
            try:
                if not cfg.radarr.archive_root:
                    raise RuntimeError("Radarr archive root is not configured")
                radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
                radarr_h = radarr_health_check(radarr_cfg)
                if not radarr_h.get("ok"):
                    raise RuntimeError(f"Radarr not reachable: {radarr_h.get('error')}")
                radarr_s = radarr_session(radarr_cfg)
                ensure_radarr_root_folder(radarr_cfg, radarr_s)
                logger.info(f"Ensured Radarr root folder exists: {cfg.radarr.archive_root}")
            except Exception as e:
                logger.warn(f"Radarr not ready for batch move: {e}")
                radarr_s = None
                radarr_cfg = None

        result: Dict[str, Any] = scan(cfg)
        global LAST_SCAN
        LAST_SCAN = result
        persist_last_scan(result)
        eligible: List[Dict[str, Any]] = result.get("eligible", [])
        ineligible_count = int(result.get("ineligibleCount", 0))

        logger.info(f"Scan: eligible={len(eligible)} ineligible={ineligible_count}")

        moved = skipped = errors = 0
        processed_items = []  # Track item names for history
        error_messages = []  # Track error reasons

        moved_by_service = {"lidarr": 0, "sonarr": 0, "radarr": 0}
        errors_by_service = {"lidarr": 0, "sonarr": 0, "radarr": 0}

        # Pause Lidarr during moves (if it is participating)
        paused = False
        if lidarr_s is not None:
            try:
                lidarr_pause(cfg, lidarr_s)
                paused = True
                logger.info("Paused Lidarr automation before archive moves")
            except Exception as e:
                logger.warn(f"Could not pause Lidarr automation: {e}")

        try:
            for item in eligible:
                service = item.get("service", "lidarr").lower()

                item_id = int(item["itemId"])
                name = item.get("itemName") or str(item_id)
                src = Path(item.get("path") or "")

                logger.info(f"Archiving [{service}] {name}")

                try:
                    if service == "lidarr":
                        if lidarr_s is None:
                            raise RuntimeError("Lidarr is not ready/configured for this move")
                        if not cfg.lidarr.archive_root:
                            raise RuntimeError("Lidarr archive root is not configured")

                        logger.info(f"Moving to: {cfg.lidarr.archive_root}")
                        payload = {
                            "artistIds": [int(item_id)],
                            "rootFolderPath": str(cfg.lidarr.archive_root),
                            "moveFiles": True,
                        }
                        lidarr_put(cfg, lidarr_s, "/api/v1/artist/editor", payload)
                        logger.info("Requested Lidarr move via editor")
                        
                        # Verify the move was successful
                        time.sleep(1)  # Brief pause for the service to update
                        updated_artist = lidarr_get(cfg, lidarr_s, f"/api/v1/artist/{item_id}")
                        new_path = updated_artist.get("path", "")
                        if str(cfg.lidarr.archive_root) in new_path:
                            logger.info(f"✓ {name} moved successfully to {new_path}")
                        else:
                            logger.warn(f"⚠ Move requested but path not yet updated: {new_path}")
                        
                        moved += 1
                        moved_by_service["lidarr"] += 1
                        processed_items.append(name)

                    elif service == "sonarr":
                        if sonarr_s is None or sonarr_cfg is None:
                            raise RuntimeError("Sonarr is not ready/configured for this move")
                        if not cfg.sonarr.archive_root:
                            raise RuntimeError("Sonarr archive root is not configured")

                        logger.info(f"Moving to: {cfg.sonarr.archive_root}")
                        payload = {
                            "seriesIds": [int(item_id)],
                            "rootFolderPath": str(cfg.sonarr.archive_root),
                            "moveFiles": True,
                        }
                        sonarr_put(sonarr_cfg, sonarr_s, "/api/v3/series/editor", payload)
                        logger.info("Requested Sonarr move via editor")
                        
                        # Verify the move was successful
                        time.sleep(1)  # Brief pause for the service to update
                        updated_series = sonarr_get(sonarr_cfg, sonarr_s, f"/api/v3/series/{item_id}")
                        new_path = updated_series.get("path", "")
                        if str(cfg.sonarr.archive_root) in new_path:
                            logger.info(f"✓ {name} moved successfully to {new_path}")
                        else:
                            logger.warn(f"⚠ Move requested but path not yet updated: {new_path}")
                        
                        moved += 1
                        moved_by_service["sonarr"] += 1
                        processed_items.append(name)

                    elif service == "radarr":
                        if radarr_s is None or radarr_cfg is None:
                            raise RuntimeError("Radarr is not ready/configured for this move")
                        if not cfg.radarr.archive_root:
                            raise RuntimeError("Radarr archive root is not configured")

                        logger.info(f"Moving to: {cfg.radarr.archive_root}")
                        payload = {
                            "movieIds": [int(item_id)],
                            "rootFolderPath": str(cfg.radarr.archive_root),
                            "moveFiles": True,
                        }
                        radarr_put(radarr_cfg, radarr_s, "/api/v3/movie/editor", payload)
                        logger.info("Requested Radarr move via editor")
                        
                        # Verify the move was successful
                        time.sleep(1)  # Brief pause for the service to update
                        updated_movie = radarr_get(radarr_cfg, radarr_s, f"/api/v3/movie/{item_id}")
                        new_path = updated_movie.get("path", "")
                        if str(cfg.radarr.archive_root) in new_path:
                            logger.info(f"✓ {name} moved successfully to {new_path}")
                        else:
                            logger.warn(f"⚠ Move requested but path not yet updated: {new_path}")
                        
                        moved += 1
                        moved_by_service["radarr"] += 1
                        processed_items.append(name)

                    else:
                        logger.warn(f"Unknown service: {service}")
                        skipped += 1
                        continue

                except Exception as e:
                    errors += 1
                    error_msg = str(e)
                    error_messages.append(f"{name}: {error_msg}")
                    logger.error(f"Failed to archive {name}: {e}")
                    if service in errors_by_service:
                        errors_by_service[service] += 1
                    continue

                if sleep_between_items > 0:
                    time.sleep(sleep_between_items)
        finally:
            if paused:
                try:
                    lidarr_resume(cfg, lidarr_s)
                    logger.info("Resumed Lidarr automation after archive moves")
                except Exception as e:
                    logger.warn(f"Could not resume Lidarr automation: {e}")

        ACTIVITY[move_id]["status"] = "complete"
        ACTIVITY[move_id]["result"] = {
            "moved": moved,
            "skipped": skipped,
            "errors": errors,
            "eligibleCount": len(eligible),
            "items": processed_items,
            "errorMessages": error_messages if error_messages else None,
            "movedByService": moved_by_service,
            "errorsByService": errors_by_service,
        }
        persist_activity()
        logger.info(f"Complete: moved={moved} skipped={skipped} errors={errors}")
        
        # Rerun scan after move completes to update eligible items
        logger.info("Running post-move scan to refresh eligible items")
        try:
            result = scan(cfg)
            LAST_SCAN = result
            persist_last_scan(result)
            logger.info(f"Post-move scan complete: eligible={len(result.get('eligible', []))} ineligible={result.get('ineligibleCount', 0)}")
        except Exception as e:
            logger.warn(f"Post-move scan failed: {e}")

    except Exception as e:
        ACTIVITY[move_id]["status"] = "error"
        ACTIVITY[move_id]["errorMessage"] = str(e)
        persist_activity()
        logger.error(f"Fatal error: {e}")


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return HTMLResponse("""
    <html>
      <head>
        <title>Archivarr</title>
        <style>
          body { font-family: system-ui; background: #111; color: #eee; padding: 30px; }
          a { color: #4ea1ff; }
          .card { background: #1e1e1e; padding: 20px; border-radius: 8px; width: 560px; }
          code { background: #222; padding: 2px 6px; border-radius: 4px; }
          .muted { color: #aaa; }
        </style>
      </head>
      <body>
        <div class="card">
          <h2>Archivarr</h2>
                    <p class="muted">Multi-service Archiver (Lidarr / Sonarr / Radarr)</p>
          <ul>
            <li><a href="/docs">API Docs</a></li>
            <li><a href="/api/v1/health">Health</a></li>
            <li><a href="/api/v1/config">Config</a></li>
          </ul>
                    <p class="muted">Lidarr missing gate: albums in <code>/api/v1/wanted/missing</code> do not block archiving.</p>
        </div>
      </body>
    </html>
    """)


@app.get("/api/v1/health")
def api_health():
    try:
        cfg = load_app_config()
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}

    if cfg is None or not _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key):
        return {"ok": False, "connected": False, "error": "Lidarr not configured"}
    return lidarr_health_check(cfg)


@app.get("/api/v1/config")
def api_get_config():
    cp = load_ini(CONFIG_PATH)
    out = {section: dict(cp[section]) for section in cp.sections()}

    # Shared HTTP settings moved to [Runtime]. For backwards compatibility,
    # if a legacy per-service key exists, surface it under Runtime.
    if "Runtime" not in out:
        out["Runtime"] = {}
    if "verify_ssl" not in out["Runtime"]:
        out["Runtime"]["verify_ssl"] = (
            out.get("Lidarr", {}).get("verify_ssl")
            or out.get("Sonarr", {}).get("verify_ssl")
            or out.get("Radarr", {}).get("verify_ssl")
            or "true"
        )
    if "timeout_sec" not in out["Runtime"]:
        out["Runtime"]["timeout_sec"] = (
            out.get("Lidarr", {}).get("timeout_sec")
            or out.get("Sonarr", {}).get("timeout_sec")
            or out.get("Radarr", {}).get("timeout_sec")
            or "30"
        )

    # Do not show legacy per-service copies in the UI.
    for section in ("Lidarr", "Sonarr", "Radarr"):
        if section in out:
            out[section].pop("verify_ssl", None)
            out[section].pop("timeout_sec", None)
    
    # Map archive roots from Archive section to their respective service sections for UI
    if "Archive" in out:
        if "lidarr_archive_root" in out["Archive"]:
            if "Lidarr" not in out:
                out["Lidarr"] = {}
            out["Lidarr"]["lidarr_archive_root"] = out["Archive"]["lidarr_archive_root"]
        
        if "sonarr_archive_root" in out["Archive"]:
            if "Sonarr" not in out:
                out["Sonarr"] = {}
            out["Sonarr"]["sonarr_archive_root"] = out["Archive"]["sonarr_archive_root"]
        
        if "radarr_archive_root" in out["Archive"]:
            if "Radarr" not in out:
                out["Radarr"] = {}
            out["Radarr"]["radarr_archive_root"] = out["Archive"]["radarr_archive_root"]
    
    return {"path": str(CONFIG_PATH), "config": out}


@app.put("/api/v1/config")
def api_save_config(config: Dict[str, Dict[str, str]]):
    cp = load_ini(CONFIG_PATH)
    
    # Extract archive roots from service sections and move to Archive section
    archive_fields = {}
    
    for section, values in config.items():
        if section not in cp:
            cp[section] = {}
        
        for key, value in values.items():
            # If this is an archive root field, save it to Archive section
            if key in ["lidarr_archive_root", "sonarr_archive_root", "radarr_archive_root"]:
                archive_fields[key] = value
            else:
                cp[section][key] = str(value)

    # Keep per-service sections clean: these are service-agnostic and belong in [Runtime].
    for section in ("Lidarr", "Sonarr", "Radarr"):
        if section in cp:
            cp[section].pop("verify_ssl", None)
            cp[section].pop("timeout_sec", None)
    
    # Ensure Archive section exists
    if "Archive" not in cp:
        cp["Archive"] = {}
    
    # Write archive root fields to Archive section
    for key, value in archive_fields.items():
        cp["Archive"][key] = str(value)
    
    save_ini(CONFIG_PATH, cp)
    return {"ok": True}


@app.post("/api/v1/scan")
def api_scan():
    """
    Scan all configured services for eligible items to archive.
    This only queries the services and does NOT create archive jobs or move files.
    """
    try:
        cfg = load_app_config()
    except Exception as e:
        # Invalid config (commonly: configured service but missing archive root)
        raise HTTPException(status_code=400, detail=str(e))
    if cfg is None:
        raise HTTPException(status_code=400, detail="App is not configured")

    lidarr_ok = _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key)
    sonarr_ok = _is_service_configured(cfg.sonarr.url, cfg.sonarr.api_key)
    radarr_ok = _is_service_configured(cfg.radarr.url, cfg.radarr.api_key)
    if not (lidarr_ok or sonarr_ok or radarr_ok):
        raise HTTPException(status_code=400, detail="No services are configured")
    scan_id = str(uuid.uuid4())
    ACTIVITY[scan_id] = {
        "id": scan_id,
        "status": "running",
        "created": time.time(),
        "log": [],
        "result": None,
        "type": "scan",
    }

    # Create logger with real-time file logging
    today = time.strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.txt"
    log_list = ACTIVITY[scan_id]["log"]
    logger = create_logger("Scan", log_list, log_file)

    try:
        logger.info("Starting scan")
        result = scan(cfg)
        global LAST_SCAN
        LAST_SCAN = result
        persist_last_scan(result)

        eligible = result.get("eligible", []) or []
        service_counts: Dict[str, int] = {"lidarr": 0, "sonarr": 0, "radarr": 0}
        for item in eligible:
            svc = str(item.get("service", "lidarr") or "lidarr").lower()
            if svc in service_counts:
                service_counts[svc] += 1

        logger.info(
            f"Scan complete: eligible={int(result.get('eligibleCount', 0) or 0)} "
            f"ineligible={int(result.get('ineligibleCount', 0) or 0)} "
            f"(lidarr={service_counts['lidarr']}, sonarr={service_counts['sonarr']}, radarr={service_counts['radarr']})"
        )

        ACTIVITY[scan_id]["status"] = "complete"
        ACTIVITY[scan_id]["result"] = {
            "eligibleCount": int(result.get("eligibleCount", 0) or 0),
            "ineligibleCount": int(result.get("ineligibleCount", 0) or 0),
            "serviceCounts": service_counts,
        }
        persist_activity()
        return result
    except Exception as e:
        logger.error(f"Scan error: {e}")
        ACTIVITY[scan_id]["status"] = "error"
        ACTIVITY[scan_id]["errorMessage"] = str(e)
        persist_activity()
        raise


@app.get("/api/v1/debug/lidarr-artists")
def api_debug_lidarr_items():
    """Debug endpoint to see raw Lidarr items (artists) and eligibility evaluation."""
    cfg = load_app_config()
    try:
        s = lidarr_session(cfg)
        artists = lidarr_get(cfg, s, "/api/v1/artist")
        
        debug_data = []
        for artist in artists[:10]:  # Show first 10
            debug_data.append({
                "id": artist.get("id"),
                "name": artist.get("artistName"),
                "monitored": artist.get("monitored"),
                "cutoffUnmet": artist.get("cutoffUnmet"),
                "missing": artist.get("missing"),
                "albumCount": artist.get("albumCount"),
                "statistics": artist.get("statistics"),
                "would_be_eligible": (
                    artist.get("monitored", True) and 
                    not artist.get("cutoffUnmet", True) and 
                    not artist.get("missing", False)
                ),
            })
        
        return {
            "total_artists": len(artists),
            "sample_debug": debug_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/debug/sonarr-series")
def api_debug_sonarr_series():
    """Debug endpoint to inspect Sonarr series fields and computed eligibility."""
    try:
        cfg = load_app_config()
        sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
        s = sonarr_session(sonarr_cfg)
        series_list = sonarr_get(sonarr_cfg, s, "/api/v3/series")

        sample = []
        for series in series_list[:10]:
            stats = series.get("statistics", {}) or {}
            total = int(stats.get("episodeCount", 0))
            files = int(stats.get("episodeFileCount", 0))
            pct = (files / total * 100) if total > 0 else 0.0
            sample.append({
                "id": series.get("id"),
                "title": series.get("title"),
                "monitored": series.get("monitored", True),
                "cutoffUnmet": series.get("cutoffUnmet"),
                "missing": series.get("missing"),
                "statistics": stats,
                "computed_percent": round(pct, 1),
                "would_be_eligible": bool(series.get("monitored", True) and files > 0 and pct >= 99.0),
            })

        return {"total_series": len(series_list), "sample_debug": sample}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/debug/radarr-movies")
def api_debug_radarr_movies():
    """Debug endpoint to inspect Radarr movie fields and computed eligibility."""
    try:
        cfg = load_app_config()
        radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
        s = radarr_session(radarr_cfg)
        movies = radarr_get(radarr_cfg, s, "/api/v3/movie")

        sample = []
        for m in movies[:10]:
            has_file = bool(m.get("hasFile", False))
            qcnm = m.get("qualityCutoffNotMet")
            cutoff_met = not (bool(qcnm) if qcnm is not None else False)
            sample.append({
                "id": m.get("id"),
                "title": m.get("title"),
                "monitored": m.get("monitored", True),
                "hasFile": has_file,
                "qualityCutoffNotMet": qcnm,
                "sizeOnDisk": m.get("sizeOnDisk", 0),
                "would_be_eligible": bool(m.get("monitored", True) and has_file and cutoff_met),
            })

        return {"total_movies": len(movies), "sample_debug": sample}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/move")
def api_move():
    """
    Execute a batch move operation on all eligible items (Lidarr/Sonarr/Radarr).
    This asks each service to move files to the configured archive roots.
    Creates a tracked job in history.
    """
    cfg = load_app_config()

    if cfg is None:
        raise HTTPException(status_code=400, detail="App is not configured")

    lidarr_ok = _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key)
    sonarr_ok = _is_service_configured(cfg.sonarr.url, cfg.sonarr.api_key)
    radarr_ok = _is_service_configured(cfg.radarr.url, cfg.radarr.api_key)
    if not (lidarr_ok or sonarr_ok or radarr_ok):
        raise HTTPException(status_code=400, detail="No services are configured")

    # Validate reachability of configured services, but only enforce checks for the
    # services that are configured.
    health = {}
    if lidarr_ok:
        health["lidarr"] = lidarr_health_check(cfg)
    if sonarr_ok:
        sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
        health["sonarr"] = sonarr_health_check(sonarr_cfg)
    if radarr_ok:
        radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
        health["radarr"] = radarr_health_check(radarr_cfg)

    failing = {k: v for k, v in health.items() if not (v or {}).get("ok")}
    if failing:
        raise HTTPException(status_code=503, detail=failing)

    move_id = str(uuid.uuid4())
    ACTIVITY[move_id] = {
        "id": move_id,
        "status": "queued",
        "created": time.time(),
        "log": [],
        "result": None,
        "type": "move",
        "mode": "batch",
        "service": "multi",
    }

    t = threading.Thread(
        target=move_job,
        args=(cfg, move_id),
        daemon=True
    )
    t.start()

    return {"moveId": move_id}


@app.get("/api/v1/move/{move_id}")
def api_move_status(move_id: str):
    if move_id not in ACTIVITY:
        raise HTTPException(status_code=404, detail="Move job not found")
    return ACTIVITY[move_id]


@app.get("/api/v1/move/{move_id}/log")
def api_move_log(move_id: str):
    if move_id not in ACTIVITY:
        raise HTTPException(status_code=404, detail="Move job not found")
    return {"lines": ACTIVITY[move_id].get("log", [])}


@app.get("/api/v1/logs/current")
def api_logs_current():
    """Get logs from the most recent scan/move job that has log output (or is currently running)."""
    if not ACTIVITY:
        return {"lines": []}

    activity_by_newest = sorted(ACTIVITY.values(), key=lambda r: r.get("created", 0), reverse=True)
    for item in activity_by_newest:
        lines = item.get("log") or []
        if lines:
            return {"lines": lines}
        if item.get("status") == "running":
            return {"lines": []}

    return {"lines": []}


@app.get("/api/v1/logs/download")
def api_logs_download(date: str = Query(...)):
    """Download logs for a specific date (YYYY-MM-DD format)."""
    from fastapi.responses import FileResponse
    log_path = LOGS_DIR / f"{date}.txt"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"No logs found for {date}")
    try:
        return FileResponse(
            path=str(log_path),
            media_type="text/plain",
            filename=f"archivarr-logs-{date}.txt"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download logs: {str(e)}")


@app.get("/api/v1/logs/available")
def api_logs_available():
    """Get list of available log dates (last 7 days)."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        available_dates = []
        for i in range(7):
            d = time.time() - (i * 24 * 60 * 60)
            date_str = time.strftime("%Y-%m-%d", time.localtime(d))
            log_path = LOGS_DIR / f"{date_str}.txt"
            if log_path.exists():
                available_dates.append(date_str)
        return {"dates": available_dates}
    except Exception as e:
        return {"dates": [], "error": str(e)}


@app.get("/api/v1/history")
def api_history():
    """
    Return all activity items (scans + moves) sorted by creation time (newest first).
    """
    # Only include history entries that have a known type.
    activity_items = [
        item for item in ACTIVITY.values()
        if item.get("type") in ["scan", "move"]
    ]
    sorted_items = sorted(
        activity_items,
        key=lambda r: r.get("created", 0),
        reverse=True
    )
    return sorted_items


@app.post("/api/v1/history/clear")
def api_history_clear():
    """Clear all stored history (scans + moves)."""
    ACTIVITY.clear()
    persist_activity()
    return {"ok": True}


def _fetch_service_stats_parallel(cfg: AppConfig):
    """Fetch stats for all services in parallel using threads to avoid timeout bottlenecks.
    
    Returns a dict with service stats. Offline services are returned with default empty values.
    """
    results = {
        "lidarr": {"ready": 0, "as_of": None, "connected": False, "url": None, "stats": {"total": 0, "with_files": 0, "total_tracks": 0, "tracks_downloaded": 0}},
        "sonarr": {"ready": 0, "as_of": None, "connected": False, "url": None, "stats": {"total": 0, "with_files": 0, "total_episodes": 0, "episodes_downloaded": 0}},
        "radarr": {"ready": 0, "as_of": None, "connected": False, "url": None, "stats": {"total": 0, "with_files": 0}},
    }
    
    def fetch_lidarr():
        try:
            if cfg.lidarr.enabled and _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key):
                results["lidarr"]["url"] = cfg.lidarr.url
                results["lidarr"]["ready"] = lidarr_get_ready_count(cfg)
                results["lidarr"]["as_of"] = time.time()
                results["lidarr"]["stats"] = lidarr_get_dashboard_stats(cfg)
                results["lidarr"]["connected"] = True
        except Exception:
            pass
    
    def fetch_sonarr():
        try:
            if cfg.sonarr.enabled and cfg.sonarr.url and cfg.sonarr.api_key:
                results["sonarr"]["url"] = cfg.sonarr.url
                sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, archive_root=cfg.sonarr.archive_root)
                results["sonarr"]["ready"] = sonarr_get_ready_count(sonarr_cfg)
                results["sonarr"]["as_of"] = time.time()
                results["sonarr"]["stats"] = sonarr_get_dashboard_stats(sonarr_cfg)
                results["sonarr"]["connected"] = True
        except Exception:
            pass
    
    def fetch_radarr():
        try:
            if cfg.radarr.enabled and cfg.radarr.url and cfg.radarr.api_key:
                results["radarr"]["url"] = cfg.radarr.url
                radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, archive_root=cfg.radarr.archive_root)
                results["radarr"]["ready"] = radarr_get_ready_count(radarr_cfg)
                results["radarr"]["as_of"] = time.time()
                results["radarr"]["stats"] = radarr_get_dashboard_stats(radarr_cfg)
                results["radarr"]["connected"] = True
        except Exception:
            pass
    
    # Run all three service checks in parallel threads
    threads = [
        threading.Thread(target=fetch_lidarr, daemon=True),
        threading.Thread(target=fetch_sonarr, daemon=True),
        threading.Thread(target=fetch_radarr, daemon=True),
    ]
    
    for thread in threads:
        thread.start()
    
    # Wait for all threads with 35-second timeout (slightly longer than individual service timeout)
    for thread in threads:
        thread.join(timeout=35)
    
    return results


@app.get("/api/v1/dashboard")
def api_dashboard():
    global LAST_SCAN
    
    # Count successful moves and failures in last 24 hours from ACTIVITY
    # Track per-service so each dashboard card updates independently.
    moves_24h_by_service = {"lidarr": 0, "sonarr": 0, "radarr": 0}
    failures_24h_by_service = {"lidarr": 0, "sonarr": 0, "radarr": 0}
    cutoff_time = time.time() - (24 * 60 * 60)
    for item in ACTIVITY.values():
        if item.get("created", 0) < cutoff_time:
            continue

        # Don't treat scans as archive "moves".
        if item.get("type") == "scan":
            continue

        status = item.get("status")
        if status not in ("complete", "error"):
            continue

        service = (item.get("service") or "").lower().strip()
        # Older entries were Lidarr-only and may not have a service field.
        if not service:
            service = "lidarr"

        # Multi-service batch jobs can report per-service counts.
        if service == "multi":
            result = item.get("result") or {}
            moved_by = result.get("movedByService") or {}
            errors_by = result.get("errorsByService") or {}
            for svc in ("lidarr", "sonarr", "radarr"):
                try:
                    moved_ = int((moved_by.get(svc, 0) or 0))
                except Exception:
                    moved_ = 0
                try:
                    errs_ = int((errors_by.get(svc, 0) or 0))
                except Exception:
                    errs_ = 0

                if status == "complete":
                    moves_24h_by_service[svc] += moved_
                    failures_24h_by_service[svc] += errs_
                else:
                    failures_24h_by_service[svc] += errs_ if errs_ else 1
            continue

        if service not in moves_24h_by_service:
            continue

        result = item.get("result") or {}
        moved = int(result.get("moved", 0) or 0)
        errors = int(result.get("errors", 0) or 0)

        if status == "complete":
            moves_24h_by_service[service] += moved
            failures_24h_by_service[service] += errors
        else:
            # Failed job: count at least one failure even if no structured result.
            failures_24h_by_service[service] += errors if errors else 1
    
    last_activity_ts = None
    if ACTIVITY:
        last_activity_ts = max(r["created"] for r in ACTIVITY.values())
    
    # Load config, but never allow dashboard to hard-fail (500) just because
    # config.ini is missing/invalid (e.g., missing archive roots).
    cfg = None
    config_error: Optional[str] = None
    try:
        cfg = load_app_config()
    except Exception as e:
        config_error = str(e)

    # Lidarr stats
    if cfg is None:
        return {
            "services": {
                "lidarr": {
                    "name": "Lidarr",
                    "url": None,
                    "configured": False,
                    "connected": False,
                    "readyToArchive": {"count": 0, "asOf": None},
                    "totalLibrary": {"count": 0},
                    "totalWithFiles": {"count": 0},
                    "totalTracks": {"count": 0},
                    "totalTracksDownloaded": {"count": 0},
                    "moves24h": {"count": moves_24h_by_service["lidarr"]},
                    "failures24h": {"count": failures_24h_by_service["lidarr"]},
                },
                "sonarr": {
                    "name": "Sonarr",
                    "url": None,
                    "configured": False,
                    "connected": False,
                    "readyToArchive": {"count": 0, "asOf": None},
                    "totalLibrary": {"count": 0},
                    "totalWithFiles": {"count": 0},
                    "totalEpisodes": {"count": 0},
                    "totalEpisodesDownloaded": {"count": 0},
                    "moves24h": {"count": moves_24h_by_service["sonarr"]},
                    "failures24h": {"count": failures_24h_by_service["sonarr"]},
                },
                "radarr": {
                    "name": "Radarr",
                    "url": None,
                    "configured": False,
                    "connected": False,
                    "readyToArchive": {"count": 0, "asOf": None},
                    "totalLibrary": {"count": 0},
                    "totalWithFiles": {"count": 0},
                    "moves24h": {"count": moves_24h_by_service["radarr"]},
                    "failures24h": {"count": failures_24h_by_service["radarr"]},
                },
            },
            "configError": config_error,
            "lastActivity": {"ts": last_activity_ts},
        }
    lidarr_ready = 0
    lidarr_as_of = None
    lidarr_connected = False
    lidarr_url = None
    lidarr_stats = {
        "total": 0,
        "with_files": 0,
        "total_tracks": 0,
        "tracks_downloaded": 0,
    }
    
    # Check Sonarr stats
    sonarr_ready = 0
    sonarr_as_of = None
    sonarr_connected = False
    sonarr_url = None
    sonarr_stats = {
        "total": 0,
        "with_files": 0,
        "total_episodes": 0,
        "episodes_downloaded": 0,
    }
    
    # Check Radarr stats
    radarr_ready = 0
    radarr_as_of = None
    radarr_connected = False
    radarr_url = None
    radarr_stats = {
        "total": 0,
        "with_files": 0,
    }
    
    # Fetch all service stats in parallel to avoid timeout bottlenecks
    service_stats = _fetch_service_stats_parallel(cfg)
    lidarr_ready = service_stats["lidarr"]["ready"]
    lidarr_as_of = service_stats["lidarr"]["as_of"]
    lidarr_connected = service_stats["lidarr"]["connected"]
    lidarr_url = service_stats["lidarr"]["url"]
    lidarr_stats = service_stats["lidarr"]["stats"]
    
    sonarr_ready = service_stats["sonarr"]["ready"]
    sonarr_as_of = service_stats["sonarr"]["as_of"]
    sonarr_connected = service_stats["sonarr"]["connected"]
    sonarr_url = service_stats["sonarr"]["url"]
    sonarr_stats = service_stats["sonarr"]["stats"]
    
    radarr_ready = service_stats["radarr"]["ready"]
    radarr_as_of = service_stats["radarr"]["as_of"]
    radarr_connected = service_stats["radarr"]["connected"]
    radarr_url = service_stats["radarr"]["url"]
    radarr_stats = service_stats["radarr"]["stats"]
    
    return {
        "services": {
            "lidarr": {
                "name": "Lidarr",
                "url": cfg.lidarr.url or None,
                "configured": _is_service_configured(cfg.lidarr.url, cfg.lidarr.api_key),
                "connected": bool(lidarr_connected),
                "readyToArchive": {"count": lidarr_ready, "asOf": lidarr_as_of},
                "totalLibrary": {"count": lidarr_stats.get("total", 0)},
                "totalWithFiles": {"count": lidarr_stats.get("with_files", 0)},
                "totalTracks": {"count": lidarr_stats.get("total_tracks", 0)},
                "totalTracksDownloaded": {"count": lidarr_stats.get("tracks_downloaded", 0)},
                "moves24h": {"count": moves_24h_by_service["lidarr"]},
                "failures24h": {"count": failures_24h_by_service["lidarr"]},
            },
            "sonarr": {
                "name": "Sonarr",
                "url": sonarr_url,
                "configured": bool(cfg.sonarr.url and cfg.sonarr.api_key),
                "connected": sonarr_connected,
                "readyToArchive": {"count": sonarr_ready, "asOf": sonarr_as_of},
                "totalLibrary": {"count": sonarr_stats.get("total", 0)},
                "totalWithFiles": {"count": sonarr_stats.get("with_files", 0)},
                "totalEpisodes": {"count": sonarr_stats.get("total_episodes", 0)},
                "totalEpisodesDownloaded": {"count": sonarr_stats.get("episodes_downloaded", 0)},
                "moves24h": {"count": moves_24h_by_service["sonarr"]},
                "failures24h": {"count": failures_24h_by_service["sonarr"]},
            },
            "radarr": {
                "name": "Radarr",
                "url": radarr_url,
                "configured": bool(cfg.radarr.url and cfg.radarr.api_key),
                "connected": radarr_connected,
                "readyToArchive": {"count": radarr_ready, "asOf": radarr_as_of},
                "totalLibrary": {"count": radarr_stats.get("total", 0)},
                "totalWithFiles": {"count": radarr_stats.get("with_files", 0)},
                "moves24h": {"count": moves_24h_by_service["radarr"]},
                "failures24h": {"count": failures_24h_by_service["radarr"]},
            },
        },
        "configError": None,
        "lastActivity": {"ts": last_activity_ts},
    }


def _fetch_eligible_items_parallel(cfg: AppConfig):
    """Fetch item maps for all services in parallel to avoid timeout bottlenecks.
    
    Returns dict with 'lidarr_map', 'sonarr_map', 'radarr_map' and availability flags.
    """
    results = {
        "lidarr_map": {},
        "lidarr_available": False,
        "sonarr_map": {},
        "sonarr_available": False,
        "radarr_map": {},
        "radarr_available": False,
    }
    
    def fetch_lidarr():
        try:
            if cfg.lidarr.enabled and cfg.lidarr.url and cfg.lidarr.api_key:
                s = lidarr_session(cfg)
                all_artists = lidarr_get(cfg, s, "/api/v1/artist")
                results["lidarr_map"] = {int(a.get("id", -1)): a for a in all_artists}
                results["lidarr_available"] = True
        except Exception:
            pass
    
    def fetch_sonarr():
        try:
            if cfg.sonarr.enabled and cfg.sonarr.url and cfg.sonarr.api_key:
                sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
                s2 = sonarr_session(sonarr_cfg)
                series_list = sonarr_get(sonarr_cfg, s2, "/api/v3/series")
                results["sonarr_map"] = {int(sx.get("id", -1)): sx for sx in series_list}
                results["sonarr_available"] = True
        except Exception:
            pass
    
    def fetch_radarr():
        try:
            if cfg.radarr.enabled and cfg.radarr.url and cfg.radarr.api_key:
                radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
                s3 = radarr_session(radarr_cfg)
                movies_list = radarr_get(radarr_cfg, s3, "/api/v3/movie")
                results["radarr_map"] = {int(mx.get("id", -1)): mx for mx in movies_list}
                results["radarr_available"] = True
        except Exception:
            pass
    
    # Run all three service checks in parallel threads
    threads = [
        threading.Thread(target=fetch_lidarr, daemon=True),
        threading.Thread(target=fetch_sonarr, daemon=True),
        threading.Thread(target=fetch_radarr, daemon=True),
    ]
    
    for thread in threads:
        thread.start()
    
    # Wait for all threads with 35-second timeout
    for thread in threads:
        thread.join(timeout=35)
    
    return results


@app.get("/api/v1/eligible")

def api_eligible():
    """Get eligible items with full details (artist name, album count, size, etc).
    
    Returns enriched items for available services. Gracefully skips services that are offline.
    Only includes items where enrichment succeeded.
    """
    global LAST_SCAN
    if not LAST_SCAN:
        return []
    
    eligible_items = LAST_SCAN.get("eligible", [])
    if not eligible_items:
        return []
    
    try:
        cfg = load_app_config()
    except Exception:
        return []
    if cfg is None:
        return []
    
    result = []
    
    # Fetch all service item maps in parallel to avoid timeout bottlenecks
    item_maps = _fetch_eligible_items_parallel(cfg)
    artist_map = item_maps["lidarr_map"]
    lidarr_available = item_maps["lidarr_available"]
    series_map = item_maps["sonarr_map"]
    sonarr_available = item_maps["sonarr_available"]
    movies_map = item_maps["radarr_map"]
    radarr_available = item_maps["radarr_available"]
    
    # Process items only if their service is available
    for item in eligible_items:
        service = item.get("service", "").lower()
        item_id = item.get("itemId")
        
        try:
            if service == "lidarr":
                if not lidarr_available:
                    # Lidarr offline - skip all Lidarr items
                    continue
                artist = artist_map.get(item_id)
                if not artist:
                    # Item not found in Lidarr - skip it
                    continue
                stats = artist.get("statistics", {})
                album_count = stats.get("albumCount", 0) or artist.get("albumCount", 0)
                size_on_disk = stats.get("sizeOnDisk", 0)
                result.append({
                    "service": "lidarr",
                    "artistId": item_id,
                    "artistName": artist.get("artistName", "Unknown"),
                    "path": artist.get("path", ""),
                    "albumCount": album_count,
                    "size": size_on_disk,
                })
            elif service == "sonarr":
                if not sonarr_available:
                    # Sonarr offline - skip all Sonarr items
                    continue
                series = series_map.get(item_id)
                if not series:
                    # Item not found in Sonarr - skip it
                    continue
                stats = series.get("statistics", {})
                total_eps = int(stats.get("episodeCount", 0))
                eps_with_files = int(stats.get("episodeFileCount", 0))
                size_on_disk = int(stats.get("sizeOnDisk", 0) or 0)
                if not size_on_disk:
                    size_on_disk = int(series.get("sizeOnDisk", 0) or 0)
                result.append({
                    "service": "sonarr",
                    "seriesId": item_id,
                    "seriesName": series.get("title", "Unknown"),
                    "path": series.get("path", ""),
                    "totalEpisodes": total_eps,
                    "episodesDownloaded": eps_with_files,
                    "size": size_on_disk,
                })
            elif service == "radarr":
                if not radarr_available:
                    # Radarr offline - skip all Radarr items
                    continue
                movie = movies_map.get(item_id)
                if not movie:
                    # Item not found in Radarr - skip it
                    continue
                size_on_disk = int(movie.get("sizeOnDisk", 0) or 0)
                result.append({
                    "service": "radarr",
                    "movieId": item_id,
                    "movieName": movie.get("title", "Unknown"),
                    "path": movie.get("path", ""),
                    "size": size_on_disk,
                })
        except Exception:
            # Skip individual item on enrichment error
            continue
    
    return result


@app.get("/api/v1/browse")
def api_browse(path: str = Query("")):
    """Browse directories on the server filesystem."""
    try:
        if not path:
            # Return root directories
            if os.name == "nt":  # Windows
                import string
                drives = []
                for drive in string.ascii_uppercase:
                    drive_path = f"{drive}:\\"
                    if os.path.exists(drive_path):
                        drives.append({"name": drive_path, "path": drive_path, "isDir": True})
                return {"path": "", "dirs": drives}
            else:  # Unix/Linux/Mac
                path = "/"
        
        browse_path = Path(path)
        if not browse_path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not browse_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        dirs = []
        try:
            for item in sorted(browse_path.iterdir()):
                if item.is_dir():
                    dirs.append({
                        "name": item.name,
                        "path": str(item),
                        "isDir": True,
                    })
        except PermissionError:
            pass
        
        return {"path": str(browse_path), "dirs": dirs}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/browse/create")
def api_create_folder(request: Dict[str, str]):
    """Create a new folder in the specified path."""
    try:
        parent_path = request.get("path", "")
        folder_name = request.get("name", "").strip()
        
        if not folder_name:
            raise ValueError("Folder name cannot be empty")
        
        # Validate folder name (no path separators, no special chars)
        if "/" in folder_name or "\\" in folder_name:
            raise ValueError("Folder name cannot contain path separators")
        
        if not parent_path:
            raise ValueError("Parent path is required")
        
        parent = Path(parent_path)
        if not parent.exists():
            raise ValueError(f"Parent path does not exist: {parent_path}")
        if not parent.is_dir():
            raise ValueError(f"Parent path is not a directory: {parent_path}")
        
        new_folder = parent / folder_name
        if new_folder.exists():
            raise ValueError(f"Folder already exists: {folder_name}")
        
        # Create the folder
        new_folder.mkdir(parents=False, exist_ok=False)
        
        return {
            "ok": True,
            "path": str(new_folder),
            "name": folder_name,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def api_get_rootfolders():
    """Get available root folders from Lidarr."""
    try:
        cfg = load_app_config()
        if cfg is None:
            return []
        s = lidarr_session(cfg)
        roots = lidarr_get(cfg, s, "/api/v1/rootfolder")
        archive_root_lower = str(cfg.lidarr.archive_root).rstrip("\\/").lower() if cfg.lidarr.archive_root else ""
        
        result = []
        for r in roots:
            path = r.get("path", "")
            path_lower = path.rstrip("\\/").lower()
            is_archive_root = path_lower == archive_root_lower
            result.append({
                "id": r.get("id"),
                "path": path,
                "isArchiveRoot": is_archive_root,
                "freeSpace": r.get("freeSpace", 0),
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/rootfolder/ensure")
def api_ensure_lidarr_rootfolder():
    """Ensure archive root folder exists in Lidarr. Create it if needed."""
    try:
        cfg = load_app_config()
        if cfg is None:
            raise HTTPException(status_code=400, detail="Lidarr not configured")
        if not cfg.lidarr.archive_root:
            raise HTTPException(status_code=400, detail="Lidarr archive root is not configured")
        s = lidarr_session(cfg)

        root_path = Path(cfg.lidarr.archive_root).expanduser()
        root_path.mkdir(parents=True, exist_ok=True)
        
        roots = lidarr_get(cfg, s, "/api/v1/rootfolder")
        target = str(root_path).rstrip("\\/").lower()
        
        for r in roots:
            p = (r.get("path") or "").rstrip("\\/").lower()
            if p == target:
                return {"ok": True, "existed": True, "path": str(root_path)}
        
        # Need defaults for quality/metadata profiles when creating a root folder
        quality_profiles = lidarr_get(cfg, s, "/api/v1/qualityprofile")
        metadata_profiles = lidarr_get(cfg, s, "/api/v1/metadataprofile")
        if not quality_profiles:
            raise HTTPException(status_code=400, detail="No Lidarr quality profiles found; cannot create root folder")
        if not metadata_profiles:
            raise HTTPException(status_code=400, detail="No Lidarr metadata profiles found; cannot create root folder")

        payload = {
            "id": 0,
            "path": str(root_path),
            "name": Path(root_path).name or str(root_path),
            "defaultQualityProfileId": int(quality_profiles[0].get("id", 0)),
            "defaultMetadataProfileId": int(metadata_profiles[0].get("id", 0)),
        }
        # Create the root folder
        lidarr_post(cfg, s, "/api/v1/rootfolder", payload)
        return {"ok": True, "existed": False, "path": str(root_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/archive/{artist_id}")
def api_archive_lidarr(artist_id: int):
    """
    Archive a specific Lidarr artist by switching its root folder and letting Lidarr move files.
    Creates a tracked job in history.
    """
    move_id = str(uuid.uuid4())
    ACTIVITY[move_id] = {
        "id": move_id,
        "status": "running",
        "created": time.time(),
        "log": [],
        "type": "move",
        "mode": "individual",
        "service": "lidarr",
        "artistName": None,  # Will be set once we fetch artist details
    }

    def _move_log(msg: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ACTIVITY[move_id].setdefault("log", []).append(f"[{timestamp}] {msg}")
    
    try:
        _move_log(f"Starting Lidarr archive: artist_id={artist_id}")
        cfg = load_app_config()
        if cfg is None:
            raise HTTPException(status_code=400, detail="Lidarr not configured")
        if not cfg.lidarr.archive_root:
            raise HTTPException(status_code=400, detail="Lidarr archive root is not configured")
        s = lidarr_session(cfg)

        # Ensure archive root folder exists in Lidarr
        ensure_lidarr_root_folder(cfg, s)
        
        # Get artist details
        artist = lidarr_get(cfg, s, f"/api/v1/artist/{artist_id}")
        artist_name = artist.get("artistName", f"artist:{artist_id}")
        ACTIVITY[move_id]["artistName"] = artist_name
        current_path = artist.get("path", "")

        _move_log(f"ARCHIVE: {artist_name}")
        _move_log(f"    to: {cfg.lidarr.archive_root}")

        payload = {
            "artistIds": [int(artist_id)],
            "rootFolderPath": str(cfg.lidarr.archive_root),
            "moveFiles": True,
        }
        lidarr_put(cfg, s, "/api/v1/artist/editor", payload)
        _move_log("  requested Lidarr move via editor")
        
        # Verify the move was successful
        time.sleep(1)  # Brief pause for Lidarr to update
        updated_artist = lidarr_get(cfg, s, f"/api/v1/artist/{artist_id}")
        new_path = updated_artist.get("path", "")
        if str(cfg.lidarr.archive_root) in new_path:
            _move_log(f"✓ {artist_name} moved successfully to {new_path}")
        else:
            _move_log(f"⚠ Move requested but path not yet updated: {new_path}")

        # Track successful move
        ACTIVITY[move_id]["status"] = "complete"
        ACTIVITY[move_id]["artistName"] = artist_name
        ACTIVITY[move_id]["result"] = {
            "moved": 1,
            "skipped": 0,
            "errors": 0,
            "eligibleCount": 1,
            "artists": [artist_name],
        }
        persist_activity()

        _move_log("Complete. moved=1 errors=0")
        
        # Rerun scan after move to refresh eligible items
        _move_log("Running post-move scan")
        try:
            result = scan(cfg)
            global LAST_SCAN
            LAST_SCAN = result
            persist_last_scan(result)
            _move_log(f"Post-move scan complete: eligible={len(result.get('eligible', []))}")
        except Exception as e:
            _move_log(f"Post-move scan failed: {e}")

        return {
            "ok": True,
            "artistId": artist_id,
            "artistName": artist_name,
            "oldPath": current_path,
            "newRootFolderPath": str(cfg.lidarr.archive_root),
        }
    except Exception as e:
        # Track failed move
        # Try to get artist name if we fetched it before the error
        artist_name = ACTIVITY[move_id].get("artistName", "Unknown Artist")
        error_msg = str(e)
        ACTIVITY[move_id]["status"] = "complete"
        ACTIVITY[move_id]["errorMessage"] = error_msg
        ACTIVITY[move_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "artists": [artist_name],
            "errorMessages": [f"{artist_name}: {error_msg}"],
        }
        persist_activity()
        _move_log(f"ERROR: {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/archive/sonarr/{series_id}")
def api_archive_sonarr(series_id: int):
    """Archive a specific Sonarr series by switching its root folder and letting Sonarr move files."""
    move_id = str(uuid.uuid4())
    ACTIVITY[move_id] = {
        "id": move_id,
        "status": "running",
        "created": time.time(),
        "log": [],
        "type": "move",
        "mode": "individual",
        "service": "sonarr",
    }

    def _move_log(msg: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ACTIVITY[move_id].setdefault("log", []).append(f"[{timestamp}] {msg}")

    try:
        _move_log(f"Starting Sonarr archive: series_id={series_id}")
        cfg = load_app_config()
        if cfg is None or not _is_service_configured(cfg.sonarr.url, cfg.sonarr.api_key):
            raise HTTPException(status_code=400, detail="Sonarr not configured")
        if not cfg.sonarr.archive_root:
            raise HTTPException(status_code=400, detail="Sonarr archive root is not configured")

        sonarr_cfg = SonarrConfig(cfg.sonarr.url, cfg.sonarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.sonarr.archive_root)
        s = sonarr_session(sonarr_cfg)
        ensure_sonarr_root_folder(sonarr_cfg, s)

        series = sonarr_get(sonarr_cfg, s, f"/api/v3/series/{series_id}")
        series_name = series.get("title") or f"series:{series_id}"
        _move_log(f"ARCHIVE: {series_name}")
        _move_log(f"  to: {cfg.sonarr.archive_root}")

        # Use the editor endpoint so Sonarr computes the destination path and moves files.
        payload = {
            "seriesIds": [int(series_id)],
            "rootFolderPath": str(cfg.sonarr.archive_root),
            "moveFiles": True,
        }
        sonarr_put(sonarr_cfg, s, "/api/v3/series/editor", payload)
        _move_log("  requested Sonarr move via editor")
        
        # Verify the move was successful
        time.sleep(1)  # Brief pause for Sonarr to update
        updated_series = sonarr_get(sonarr_cfg, s, f"/api/v3/series/{series_id}")
        new_path = updated_series.get("path", "")
        if str(cfg.sonarr.archive_root) in new_path:
            _move_log(f"✓ {series_name} moved successfully to {new_path}")
        else:
            _move_log(f"⚠ Move requested but path not yet updated: {new_path}")

        ACTIVITY[move_id]["status"] = "complete"
        ACTIVITY[move_id]["result"] = {
            "moved": 1,
            "skipped": 0,
            "errors": 0,
            "eligibleCount": 1,
            "items": [series_name],
        }
        persist_activity()

        _move_log("Complete. moved=1 errors=0")
        
        # Rerun scan after move to refresh eligible items
        _move_log("Running post-move scan")
        try:
            result = scan(cfg)
            global LAST_SCAN
            LAST_SCAN = result
            persist_last_scan(result)
            _move_log(f"Post-move scan complete: eligible={len(result.get('eligible', []))}")
        except Exception as e:
            _move_log(f"Post-move scan failed: {e}")

        return {"ok": True, "seriesId": int(series_id), "seriesName": series_name}
    except HTTPException as e:
        ACTIVITY[move_id]["status"] = "error"
        ACTIVITY[move_id]["errorMessage"] = str(e.detail)
        ACTIVITY[move_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "items": [f"series:{series_id}"],
            "errorMessages": [str(e.detail)],
        }
        persist_activity()
        _move_log(f"ERROR: {e.detail}")
        raise
    except Exception as e:
        ACTIVITY[move_id]["status"] = "error"
        ACTIVITY[move_id]["errorMessage"] = str(e)
        ACTIVITY[move_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "items": [f"series:{series_id}"],
            "errorMessages": [str(e)],
        }
        persist_activity()
        _move_log(f"ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/archive/radarr/{movie_id}")
def api_archive_radarr(movie_id: int):
    """Archive a specific Radarr movie by switching its root folder and letting Radarr move files."""
    move_id = str(uuid.uuid4())
    ACTIVITY[move_id] = {
        "id": move_id,
        "status": "running",
        "created": time.time(),
        "log": [],
        "type": "move",
        "mode": "individual",
        "service": "radarr",
    }

    def _move_log(msg: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ACTIVITY[move_id].setdefault("log", []).append(f"[{timestamp}] {msg}")

    try:
        _move_log(f"Starting Radarr archive: movie_id={movie_id}")
        cfg = load_app_config()
        if cfg is None or not _is_service_configured(cfg.radarr.url, cfg.radarr.api_key):
            raise HTTPException(status_code=400, detail="Radarr not configured")
        if not cfg.radarr.archive_root:
            raise HTTPException(status_code=400, detail="Radarr archive root is not configured")

        radarr_cfg = RadarrConfig(cfg.radarr.url, cfg.radarr.api_key, cfg.verify_ssl, cfg.timeout_sec, cfg.radarr.archive_root)
        s = radarr_session(radarr_cfg)
        ensure_radarr_root_folder(radarr_cfg, s)

        movie = radarr_get(radarr_cfg, s, f"/api/v3/movie/{movie_id}")
        movie_name = movie.get("title") or f"movie:{movie_id}"
        _move_log(f"ARCHIVE: {movie_name}")
        _move_log(f"  to: {cfg.radarr.archive_root}")

        payload = {
            "movieIds": [int(movie_id)],
            "rootFolderPath": str(cfg.radarr.archive_root),
            "moveFiles": True,
        }
        radarr_put(radarr_cfg, s, "/api/v3/movie/editor", payload)
        _move_log("  requested Radarr move via editor")
        
        # Verify the move was successful
        time.sleep(1)  # Brief pause for Radarr to update
        updated_movie = radarr_get(radarr_cfg, s, f"/api/v3/movie/{movie_id}")
        new_path = updated_movie.get("path", "")
        if str(cfg.radarr.archive_root) in new_path:
            _move_log(f"✓ {movie_name} moved successfully to {new_path}")
        else:
            _move_log(f"⚠ Move requested but path not yet updated: {new_path}")

        ACTIVITY[move_id]["status"] = "complete"
        ACTIVITY[move_id]["result"] = {
            "moved": 1,
            "skipped": 0,
            "errors": 0,
            "eligibleCount": 1,
            "items": [movie_name],
        }
        persist_activity()

        _move_log("Complete. moved=1 errors=0")
        
        # Rerun scan after move to refresh eligible items
        _move_log("Running post-move scan")
        try:
            result = scan(cfg)
            global LAST_SCAN
            LAST_SCAN = result
            persist_last_scan(result)
            _move_log(f"Post-move scan complete: eligible={len(result.get('eligible', []))}")
        except Exception as e:
            _move_log(f"Post-move scan failed: {e}")

        return {"ok": True, "movieId": int(movie_id), "movieName": movie_name}
    except HTTPException as e:
        ACTIVITY[move_id]["status"] = "error"
        ACTIVITY[move_id]["errorMessage"] = str(e.detail)
        ACTIVITY[move_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "items": [f"movie:{movie_id}"],
            "errorMessages": [str(e.detail)],
        }
        persist_activity()
        _move_log(f"ERROR: {e.detail}")
        raise
    except Exception as e:
        ACTIVITY[move_id]["status"] = "error"
        ACTIVITY[move_id]["errorMessage"] = str(e)
        ACTIVITY[move_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "items": [f"movie:{movie_id}"],
            "errorMessages": [str(e)],
        }
        persist_activity()
        _move_log(f"ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8787)
