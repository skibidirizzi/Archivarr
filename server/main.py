from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI(title="Archivarr", version="0.1.0")

# --- API placeholder ---
@app.get("/api/v1/health")
def health():
    return {"ok": True, "app": "Archivarr"}

# --- Serve built UI ---
DIST_DIR = Path(__file__).resolve().parents[1] / "ui" / "dist"
ASSETS_DIR = DIST_DIR / "assets"
INDEX_FILE = DIST_DIR / "index.html"

# Mount assets if present
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

# Serve the SPA index for app routes (client-side routing)
@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    if INDEX_FILE.exists():
        return FileResponse(str(INDEX_FILE))
    return {"error": "UI not built. Run `npm run build` in /ui first."}
