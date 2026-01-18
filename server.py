from __future__ import annotations

import configparser
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from lidarr_client import (
    AppConfig,
    lidarr_session,
    lidarr_get,
    lidarr_post,
    lidarr_put,
    lidarr_pause,
    lidarr_resume,
    health_check,
)
from storage import load_json_file, save_json_file, load_ini, save_ini


# ------------------------------------------------------------------------------
# App + Paths
# ------------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("LIDARR_CUTOFF_CONFIG", APP_DIR / "config.ini"))
DATA_DIR = APP_DIR / "data"
LAST_SCAN_FILE = DATA_DIR / "last_scan.json"
RUNS_FILE = DATA_DIR / "runs.json"

app = FastAPI(title="Archivarr")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS: Dict[str, Dict[str, Any]] = {}
LAST_SCAN: Optional[Dict[str, Any]] = None
ARCHIVE_ROOT: Optional[str] = None
LOGS_DIR = APP_DIR / "logs"


# ------------------------------------------------------------------------------
# Data Persistence Helpers
# ------------------------------------------------------------------------------

def _norm_url(url: str) -> str:
    return (url or "").rstrip("/")


def persist_last_scan(scan_result: Dict[str, Any]) -> None:
    """Save last scan results to disk."""
    save_json_file(LAST_SCAN_FILE, scan_result)


def persist_runs() -> None:
    """Save run tracking data to disk."""
    save_json_file(RUNS_FILE, RUNS)


LAST_SCAN = load_json_file(LAST_SCAN_FILE)
RUNS = load_json_file(RUNS_FILE) or {}

# ------------------------------------------------------------------------------
# UI Wiring Models
# ------------------------------------------------------------------------------

class LidarrConnection(BaseModel):
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

    cfg = AppConfig(
        lidarr_url=_norm_url(cp.get("Lidarr", "url").strip()),
        lidarr_api_key=cp.get("Lidarr", "api_key").strip(),
        verify_ssl=cp.getboolean("Lidarr", "verify_ssl", fallback=True),
        timeout_sec=cp.getint("Lidarr", "timeout_sec", fallback=30),

        archive_root=Path(cp.get("Archive", "archive_root")),

        sleep_between_artists=cp.getfloat("Runtime", "sleep_between_artists", fallback=0.0),
        limit_artists=cp.getint("Runtime", "limit_artists", fallback=0),

        verbose_log=cp.getboolean("Runtime", "verbose_log", fallback=False),

        missing_page_size=cp.getint("Runtime", "missing_page_size", fallback=2000),
        missing_max_pages=cp.getint("Runtime", "missing_max_pages", fallback=50),
    )

    global ARCHIVE_ROOT
    ARCHIVE_ROOT = str(cfg.archive_root)

    if not cfg.lidarr_api_key:
        raise ValueError("config.ini: [Lidarr] api_key is empty")
    if not str(cfg.archive_root).strip():
        raise ValueError("config.ini: [Archive] archive_root is empty")

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

    # Preserve existing defaults if already present
    if "verify_ssl" not in cp["Lidarr"]:
        cp["Lidarr"]["verify_ssl"] = "true"
    if "timeout_sec" not in cp["Lidarr"]:
        cp["Lidarr"]["timeout_sec"] = "30"

    save_ini(CONFIG_PATH, cp)
    return {"ok": True}


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

    lidarr_status = r.json()
    return {"ok": True, "status": {"version": lidarr_status.get("version", "unknown")}}


@app.get("/api/v1/status")
def api_status():
    # UI chips endpoint
    try:
        cfg = load_app_config()
        if cfg is None:
            return {
                "configured": False,
                "lidarr": {"ok": False, "connected": False, "error": "Not configured"},
                "scheduler": {"enabled": False},
                "lastRun": None,
            }

        h = health_check(cfg)

        last_run_ts = None
        if RUNS:
            last_run_ts = max(r["created"] for r in RUNS.values())

        return {
            "configured": True,
            "lidarr": h,
            "scheduler": {"enabled": False},
            "lastRun": last_run_ts,
        }
    except Exception as e:
        return {
            "configured": False,
            "lidarr": {"ok": False, "error": str(e)},
            "scheduler": {"enabled": False},
            "lastRun": None,
        }


# ------------------------------------------------------------------------------
# Setup endpoints
# ------------------------------------------------------------------------------

@app.get("/api/v1/setup/status")
def api_setup_status():
    """Check if the app is configured."""
    return {"configured": CONFIG_PATH.exists()}


class SetupConfig(BaseModel):
    lidarr_url: str
    lidarr_api_key: str
    archive_root: str
    verify_ssl: bool = True
    timeout_sec: int = 30
    limit_artists: int = 0
    verbose_log: bool = False
    missing_page_size: int = 2000
    missing_max_pages: int = 50


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

        cp["Lidarr"] = {
            "url": _norm_url(setup.lidarr_url.strip()),
            "api_key": setup.lidarr_api_key.strip(),
            "verify_ssl": "true" if setup.verify_ssl else "false",
            "timeout_sec": str(setup.timeout_sec),
        }

        cp["Archive"] = {
            "archive_root": setup.archive_root.strip(),
            "sleep_between_artists": "3",
        }

        cp["Runtime"] = {
            "limit_artists": str(setup.limit_artists),
            "verbose_log": "true" if setup.verbose_log else "false",
            "missing_page_size": str(setup.missing_page_size),
            "missing_max_pages": str(setup.missing_max_pages),
        }

        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Write config file using storage module
        save_ini(CONFIG_PATH, cp)

        # Now load the config into memory to initialize ARCHIVE_ROOT
        cfg = load_app_config()
        if cfg is None:
            raise ValueError("Failed to load config after saving")

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

    page_size = max(1, int(cfg.missing_page_size or 2000))
    max_pages = max(1, int(cfg.missing_max_pages or 50))

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

def ensure_root_folder(cfg: AppConfig, s: requests.Session) -> None:
    # Ensure the path exists on disk before asking Lidarr to add it; Lidarr returns 400 otherwise.
    root_path = Path(cfg.archive_root).expanduser()
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


def safe_move_artist_folder(src: Path, dest_root: Path) -> Path:
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / src.name
    if dest.exists():
        raise FileExistsError(f"Destination already exists: {dest}")
    if not src.exists():
        raise FileNotFoundError(f"Source artist path missing: {src}")
    shutil.move(str(src), str(dest))
    return dest


def _save_logs_to_file(log: List[str]) -> None:
    """Save run logs to disk for historical access."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        log_path = LOGS_DIR / f"{today}.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            for entry in log:
                f.write(entry + "\n")
    except Exception as e:
        print(f"Failed to save logs: {e}")


# ------------------------------------------------------------------------------
# Archive Scanning & Execution
# ------------------------------------------------------------------------------

def scan(cfg: AppConfig) -> Dict[str, Any]:
    s = lidarr_session(cfg)

    missing_album_ids = fetch_missing_album_ids(cfg, s)

    profiles = lidarr_get(cfg, s, "/api/v1/qualityprofile")
    profile_map: Dict[int, dict] = {int(p["id"]): p for p in profiles}

    artists = lidarr_get(cfg, s, "/api/v1/artist")
    if cfg.limit_artists and cfg.limit_artists > 0:
        artists = artists[: cfg.limit_artists]

    eligible: List[dict] = []
    ineligible: List[dict] = []

    for artist in artists:
        artist_id = int(artist["id"])
        name = artist.get("artistName") or f"artist:{artist_id}"
        artist_path = artist.get("path") or ""
        size = artist.get("statistics", {}).get("sizeOnDisk", 0)
        prof_id = int(artist.get("qualityProfileId") or 0)

        if not artist.get("monitored", True):
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": ["Artist not monitored"],
                "albumFailures": [],
            })
            continue

        prof = profile_map.get(prof_id)
        if not prof:
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": [f"Missing quality profile id={prof_id}"],
                "albumFailures": [],
            })
            continue

        cutoff_id = _extract_cutoff_id(prof)
        cutoff_format_score = int(prof.get("cutoffFormatScore") or 0)
        upgrade_allowed = prof.get("upgradeAllowed", True)

        ordered, group_members, group_names = flatten_quality_profile(prof.get("items") or [])

        better = cfg.better_is_lower_index
        if better is None:
            better = autodetect_better_direction(ordered)

        rank_map = build_quality_rank_map(ordered, better)
        group_rank_map = build_group_rank_map(group_members, rank_map)

        cutoff_is_group = False
        if cutoff_id in rank_map:
            cutoff_rank = rank_map[cutoff_id]
            cutoff_label = next((n for (qid, n) in ordered if qid == cutoff_id), f"quality:{cutoff_id}")
        elif cutoff_id in group_rank_map:
            cutoff_is_group = True
            cutoff_rank = group_rank_map[cutoff_id]
            cutoff_label = group_names.get(cutoff_id, f"group:{cutoff_id}")
        else:
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": [
                    f"Cutoff id={cutoff_id} not found as quality or group in profile",
                    f"FirstFewQualities={ordered[:10]}",
                    f"GroupsSeen={sorted(list(group_names.items()))[:10]}",
                    f"Raw cutoff field={prof.get('cutoff')}",
                ],
                "albumFailures": [],
            })
            continue

        albums = lidarr_get(cfg, s, "/api/v1/album", params={"artistId": artist_id})

        album_failures: List[dict] = []
        any_monitored_album = False
        any_evaluated_album = False

        skipped_missing = 0
        skipped_no_files = 0
        missing_failures = 0

        for alb in albums:
            if not alb.get("monitored", True):
                continue

            any_monitored_album = True
            album_id = int(alb["id"])
            title = alb.get("title") or f"album:{album_id}"

            if album_id in missing_album_ids:
                skipped_missing += 1
                missing_failures += 1
                album_failures.append({
                    "albumId": album_id,
                    "title": title,
                    "reasons": ["Album has missing tracks (wanted/missing)"],
                })
                continue

            stats = alb.get("statistics") or {}
            tf_count = int(stats.get("trackFileCount") or 0)

            if tf_count <= 0:
                skipped_no_files += 1
                album_failures.append({
                    "albumId": album_id,
                    "title": title,
                    "reasons": ["Album has no track files"],
                })
                continue

            any_evaluated_album = True

            trackfiles = lidarr_get(cfg, s, "/api/v1/trackfile", params={"albumId": [album_id]})

            ok, reasons = evaluate_album_cutoff(
                album=alb,
                trackfiles=trackfiles,
                rank_map=rank_map,
                cutoff_rank=cutoff_rank,
                cutoff_id=cutoff_id,
                cutoff_label=cutoff_label,
                cutoff_format_score=cutoff_format_score,
                enforce_format_score=cfg.enforce_format_score,
            )

            if not ok:
                album_failures.append({
                    "albumId": album_id,
                    "title": title,
                    "reasons": reasons,
                })

        skipped_unavailable = skipped_missing + skipped_no_files

        if not any_monitored_album:
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": ["No monitored albums"],
                "albumFailures": [],
            })
            continue

        if not any_evaluated_album:
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": [
                    "No non-missing monitored albums with files to evaluate",
                    f"Skipped unavailable albums={skipped_unavailable}",
                ],
                "albumFailures": [],
                "skipped": {
                    "unavailable": skipped_unavailable,
                    "missing": skipped_missing,
                    "noFiles": skipped_no_files,
                },
            })
            continue

        if album_failures:
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": [
                    "One or more monitored, non-missing albums with files did not meet cutoff",
                    f"Skipped unavailable albums={skipped_unavailable}",
                ],
                "albumFailures": album_failures,
                "skipped": {
                    "unavailable": skipped_unavailable,
                    "missing": skipped_missing,
                    "noFiles": skipped_no_files,
                },
            })
            continue

        # Check if artist is already in archive root
        current_path = Path(artist_path)
        if current_path.parent.resolve() == Path(ARCHIVE_ROOT).resolve():
            ineligible.append({
                "artistId": artist_id,
                "artistName": name,
                "path": artist_path,
                "reasons": ["Already in archive root folder"],
                "albumFailures": [],
            })
            continue

        eligible.append({
            "artistId": artist_id,
            "artistName": name,
            "path": artist_path,
            "size": size,
            "qualityProfileId": prof_id,
            "cutoffId": cutoff_id,
            "cutoffLabel": cutoff_label,
            "cutoffIsGroup": cutoff_is_group,
            "betterIsLowerIndex": better,
            "skippedUnavailableAlbums": skipped_unavailable,
            "albumCount": len(albums),
            "targetRoot": ARCHIVE_ROOT,
            "upgradeAllowed": upgrade_allowed,
            "skipped": {
                "unavailable": skipped_unavailable,
                "missing": skipped_missing,
                "noFiles": skipped_no_files,
            },
        })

    return {
        "eligibleCount": len(eligible),
        "ineligibleCount": len(ineligible),
        "eligible": eligible,
        "ineligible": ineligible,
    }


def run_job(cfg: AppConfig, run_id: str) -> None:
    RUNS[run_id]["status"] = "running"
    log: List[str] = RUNS[run_id].setdefault("log", [])

    def info(msg: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        log.append(entry)

    s = lidarr_session(cfg)

    try:
        info(f"Starting batch archive run")

        h = health_check(cfg)
        if not h.get("ok"):
            raise RuntimeError(f"Lidarr not reachable: {h.get('error')}")

        # Ensure archive root exists
        ensure_root_folder(cfg, s)
        info(f"Ensured Lidarr root folder exists: {cfg.archive_root}")

        result: Dict[str, Any] = scan(cfg)
        global LAST_SCAN
        LAST_SCAN = result
        persist_last_scan(result)
        eligible: List[Dict[str, Any]] = result.get("eligible", [])
        ineligible_count = int(result.get("ineligibleCount", 0))

        info(f"Scan: eligible={len(eligible)} ineligible={ineligible_count}")

        moved = skipped = errors = 0
        processed_artists = []  # Track artist names for history
        error_messages = []  # Track error reasons

        # Pause Lidarr during moves
        paused = False
        try:
            lidarr_pause(cfg, s)
            paused = True
            info("Paused Lidarr automation before archive moves")
        except Exception as e:
            info(f"  WARN: could not pause Lidarr automation: {e}")

        try:
            for a in eligible:
                artist_id = int(a["artistId"])
                name = a.get("artistName") or str(artist_id)
                src = Path(a["path"])
                dest = cfg.archive_root / src.name

                info(f"ARCHIVE: {name}")
                info(f"  from: {src}")
                info(f"    to: {dest}")

                try:
                    all_artists = lidarr_get(cfg, s, "/api/v1/artist")
                    artist_obj = next((x for x in all_artists if int(x.get("id", -1)) == artist_id), None)
                    if not artist_obj:
                        raise RuntimeError("Could not load artist object for PUT update")

                    dest_path = cfg.archive_root / src.name

                    artist_obj["rootFolderPath"] = str(cfg.archive_root)
                    artist_obj["path"] = str(dest_path)
                    artist_obj["moveFiles"] = True  # Let Lidarr perform the move

                    max_attempts = 3
                    for attempt in range(1, max_attempts + 1):
                        try:
                            lidarr_put(cfg, s, f"/api/v1/artist/{artist_id}", artist_obj)
                            info(f"  requested Lidarr move -> {dest_path} (attempt {attempt})")
                            moved += 1
                            processed_artists.append(name)
                            break
                        except Exception as move_err:
                            if attempt == max_attempts:
                                raise
                            info(f"  WARN: move attempt {attempt} failed ({move_err}); retrying...")
                            time.sleep(2 * attempt)

                except Exception as e:
                    errors += 1
                    error_msg = str(e)
                    error_messages.append(f"{name}: {error_msg}")
                    info(f"  ERROR: {e}")
                    continue

                if cfg.sleep_between_artists and cfg.sleep_between_artists > 0:
                    time.sleep(cfg.sleep_between_artists)
        finally:
            if paused:
                try:
                    lidarr_resume(cfg, s)
                    info("Resumed Lidarr automation after archive moves")
                except Exception as e:
                    info(f"  WARN: could not resume Lidarr automation: {e}")

        RUNS[run_id]["status"] = "complete"
        RUNS[run_id]["result"] = {
            "moved": moved,
            "skipped": skipped,
            "errors": errors,
            "eligibleCount": len(eligible),
            "artists": processed_artists,
            "errorMessages": error_messages if error_messages else None,
        }
        persist_runs()
        info(f"Complete. moved={moved} skipped={skipped} errors={errors}")
        _save_logs_to_file(log)

    except Exception as e:
        RUNS[run_id]["status"] = "error"
        RUNS[run_id]["errorMessage"] = str(e)
        persist_runs()
        info(f"FATAL ERROR: {e}")
        _save_logs_to_file(log)


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
          <p class="muted">Lidarr Cutoff Archiver</p>
          <ul>
            <li><a href="/docs">API Docs</a></li>
            <li><a href="/api/v1/health">Health</a></li>
            <li><a href="/api/v1/config">Config</a></li>
          </ul>
          <p class="muted">Missing gate: albums in <code>/api/v1/wanted/missing</code> do not block archiving.</p>
        </div>
      </body>
    </html>
    """)


@app.get("/api/v1/health")
def api_health():
    cfg = load_app_config()
    return health_check(cfg)


@app.get("/api/v1/config")
def api_get_config():
    cp = load_ini(CONFIG_PATH)
    out = {section: dict(cp[section]) for section in cp.sections()}
    return {"path": str(CONFIG_PATH), "config": out}


@app.put("/api/v1/config")
def api_save_config(config: Dict[str, Dict[str, str]]):
    cp = load_ini(CONFIG_PATH)
    for section, values in config.items():
        if section not in cp:
            cp[section] = {}
        for key, value in values.items():
            cp[section][key] = str(value)
    save_ini(CONFIG_PATH, cp)
    return {"ok": True}


@app.post("/api/v1/scan")
def api_scan():
    """
    Scan Lidarr for eligible artists to archive.
    This only queries Lidarr and does NOT create archive jobs or move files.
    """
    cfg = load_app_config()
    h = health_check(cfg)
    if not h.get("ok"):
        raise HTTPException(status_code=503, detail=h)
    result = scan(cfg)
    global LAST_SCAN
    LAST_SCAN = result
    persist_last_scan(result)
    return result


@app.post("/api/v1/run")
def api_run():
    """
    Execute a batch archive operation on all eligible artists.
    This will actually move files to the archive root.
    Creates a tracked job in history.
    """
    cfg = load_app_config()
    h = health_check(cfg)
    if not h.get("ok"):
        raise HTTPException(status_code=503, detail=h)

    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "id": run_id,
        "status": "queued",
        "created": time.time(),
        "log": [],
        "result": None,
        "type": "batch",  # Mark as batch archive operation
    }

    t = threading.Thread(
        target=run_job,
        args=(cfg, run_id),
        daemon=True
    )
    t.start()

    return {"runId": run_id}


@app.get("/api/v1/run/{run_id}")
def api_run_status(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUNS[run_id]


@app.get("/api/v1/run/{run_id}/log")
def api_run_log(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"lines": RUNS[run_id].get("log", [])}


@app.get("/api/v1/logs/current")
def api_logs_current():
    """Get logs from the most recent run."""
    if not RUNS:
        return {"lines": []}
    latest_run = max(RUNS.values(), key=lambda r: r.get("created", 0))
    return {"lines": latest_run.get("log", [])}


@app.get("/api/v1/logs/download")
def api_logs_download(date: str = Query(...)):
    """Download logs for a specific date (YYYY-MM-DD format)."""
    from fastapi.responses import FileResponse
    log_path = LOGS_DIR / f"{date}.txt"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"No logs found for {date}")
    return FileResponse(log_path, media_type="text/plain", filename=f"archivarr-logs-{date}.txt")


@app.get("/api/v1/history")
def api_history():
    """
    Return all archive operations (batch and individual) sorted by creation time (newest first).
    Scans are NOT included - only actual archive jobs that move files.
    """
    # Only include runs that have a type field (batch or individual archives)
    # This excludes any scan operations which never create RUNS entries
    archive_runs = [
        run for run in RUNS.values()
        if run.get("type") in ["batch", "individual"]
    ]
    sorted_runs = sorted(
        archive_runs,
        key=lambda r: r.get("created", 0),
        reverse=True
    )
    return sorted_runs


@app.get("/api/v1/dashboard")
def api_dashboard():
    global LAST_SCAN
    ready_count = LAST_SCAN["eligibleCount"] if LAST_SCAN else 0
    as_of = time.time() if LAST_SCAN else None
    connected = 1 if LAST_SCAN else 0  # assume connected if scan done
    last_run_ts = None
    if RUNS:
        last_run_ts = max(r["created"] for r in RUNS.values())
    
    # Count successful moves and failures in last 24 hours from RUNS
    moves_24h = 0
    failures_24h = 0
    cutoff_time = time.time() - (24 * 60 * 60)
    for run in RUNS.values():
        if run.get("created", 0) >= cutoff_time and run.get("status") == "complete":
            result = run.get("result", {})
            moves_24h += result.get("moved", 0)
            failures_24h += result.get("errors", 0)
    
    return {
        "readyToArchive": {"count": ready_count, "asOf": as_of},
        "moves24h": {"count": moves_24h},
        "failures24h": {"count": failures_24h},
        "connectedApps": {"count": connected},
        "lastRun": {"ts": last_run_ts},
    }


@app.get("/api/v1/eligible")
def api_eligible():
    global LAST_SCAN
    return LAST_SCAN.get("eligible", []) if LAST_SCAN else []


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
def api_get_rootfolders():
    """Get available root folders from Lidarr."""
    try:
        cfg = load_app_config()
        s = lidarr_session(cfg)
        roots = lidarr_get(cfg, s, "/api/v1/rootfolder")
        archive_root_lower = str(ARCHIVE_ROOT).rstrip("\\/").lower() if ARCHIVE_ROOT else ""
        
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
def api_ensure_rootfolder():
    """Ensure archive root folder exists in Lidarr. Create it if needed."""
    try:
        cfg = load_app_config()
        s = lidarr_session(cfg)

        root_path = Path(ARCHIVE_ROOT).expanduser()
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
def api_archive(artist_id: int):
    """
    Archive a specific artist by moving folder to archive root and updating Lidarr.
    This actually moves files and should only be run manually.
    Creates a tracked job in history.
    """
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "id": run_id,
        "status": "running",
        "created": time.time(),
        "log": [],
        "type": "individual",  # Mark as individual archive operation
        "artistName": None,  # Will be set once we fetch artist details
    }
    
    try:
        cfg = load_app_config()
        s = lidarr_session(cfg)

        # Ensure archive root folder exists in Lidarr
        ensure_root_folder(cfg, s)
        
        # Get artist details
        artist = lidarr_get(cfg, s, f"/api/v1/artist/{artist_id}")
        artist_name = artist.get("artistName", f"artist:{artist_id}")
        current_path = artist.get("path", "")

        if not current_path:
            raise ValueError("Artist has no path configured")

        src_path = Path(current_path)
        if not src_path.exists():
            raise FileNotFoundError(f"Artist folder not found: {current_path}")

        # Move the artist folder to archive root
        archive_dest = safe_move_artist_folder(src_path, Path(ARCHIVE_ROOT))
        
        # Update Lidarr with new path
        artist["path"] = str(archive_dest)
        lidarr_put(cfg, s, f"/api/v1/artist/{artist_id}", artist)

        # Track successful move
        RUNS[run_id]["status"] = "complete"
        RUNS[run_id]["artistName"] = artist_name
        RUNS[run_id]["result"] = {
            "moved": 1,
            "skipped": 0,
            "errors": 0,
            "eligibleCount": 1,
            "artists": [artist_name],
        }
        persist_runs()

        return {
            "ok": True,
            "artistId": artist_id,
            "artistName": artist_name,
            "oldPath": current_path,
            "newPath": str(archive_dest),
        }
    except Exception as e:
        # Track failed move
        # Try to get artist name if we fetched it before the error
        artist_name = RUNS[run_id].get("artistName", "Unknown Artist")
        error_msg = str(e)
        RUNS[run_id]["status"] = "complete"
        RUNS[run_id]["errorMessage"] = error_msg
        RUNS[run_id]["result"] = {
            "moved": 0,
            "skipped": 0,
            "errors": 1,
            "eligibleCount": 1,
            "artists": [artist_name],
            "errorMessages": [f"{artist_name}: {error_msg}"],
        }
        persist_runs()
        raise HTTPException(status_code=500, detail=str(e))
