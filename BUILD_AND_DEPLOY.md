# Archivarr - Build & Deployment Guide

## Overview

Archivarr is a multi-service media archiver with a Python FastAPI backend and React frontend. This guide covers building executable installers for Windows distribution.

## Prerequisites

- Python 3.11+ (with pip)
- Node.js 18+ (with npm)
- Windows 10/11
- Optional: NSIS (Nullsoft Scriptable Install System) for professional installers

## Build Process

### 1. Build the Frontend

The React frontend must be built before creating the executable:

```bash
cd ui
npm install      # First time only
npm run build    # Creates ui/dist/ with optimized assets
```

Output: `ui/dist/` containing `index.html`, `assets/`, and `vite.svg`

### 2. Build the Python Executable

The spec file (`archivarr.spec`) includes all dependencies and the built frontend:

```bash
# Install PyInstaller (if not already installed)
pip install pyinstaller

# Build the executable
python -m PyInstaller archivarr.spec
```

Output:
- `dist/Archivarr.exe` - Standalone executable (~250MB)
- `dist/Archivarr/` - Distribution folder with all dependencies

### 3. Create the Windows Installer (Optional)

To create a professional Windows installer with Start Menu shortcuts and uninstall functionality:

**Option A: Using NSIS (Recommended)**

1. Download and install [NSIS](https://nsis.sourceforge.io/download)
2. Build the installer:
   ```bash
   "C:\Program Files (x86)\NSIS\makensis.exe" installer.nsi
   ```
   Output: `Archivarr-Installer.exe`

**Option B: Manual Distribution**

Simply distribute the `dist/Archivarr/` folder to users who can run `Archivarr.exe` directly.

## Running Archivarr

### From Command Line

```bash
python server.py          # Development
# or
dist/Archivarr/Archivarr.exe   # Standalone executable
```

### Configuration

1. Edit `config.ini` to set up services:
   ```ini
   [lidarr]
   url=http://localhost:8686
   api_key=your_api_key
   archive_root=/mnt/archive
   enabled=true
   
   [sonarr]
   url=http://localhost:8989
   api_key=your_api_key
   archive_root=/mnt/archive
   enabled=true
   
   [radarr]
   url=http://localhost:7878
   api_key=your_api_key
   archive_root=/mnt/archive
   enabled=true
   ```

2. Start the application - it will listen on `http://localhost:8787`

## Features

✅ Real-time logging with disk persistence (`logs/YYYY-MM-DD.txt`)
✅ Parallel service health checks (prevents timeouts)
✅ Service enable/disable toggles in Settings
✅ Graceful degradation when services are offline
✅ Automatic page refresh after operations
✅ Move verification with API confirmation
✅ Post-move automatic scans
✅ Built-in React UI served from backend

## Project Structure

```
Archivarr/
├── server.py              # FastAPI backend (main entry point)
├── app_config.py          # Configuration dataclasses
├── logger.py              # Real-time dual-write logger
├── lidarr_client.py       # Lidarr API integration
├── sonarr_client.py       # Sonarr API integration
├── radarr_client.py       # Radarr API integration
├── storage.py             # Storage management
├── config.ini             # Configuration file
├── archivarr.spec         # PyInstaller specification
├── installer.nsi          # NSIS installer script
├── ui/                    # React frontend
│   ├── dist/              # Built frontend (generated)
│   ├── src/               # React source code
│   ├── package.json
│   └── vite.config.ts
├── data/                  # Runtime data (activity, scan results)
└── logs/                  # Log files (generated)
```

## Troubleshooting

### Executable won't start
- Ensure `config.ini` exists in the same directory as `Archivarr.exe`
- Check `logs/` directory for error messages
- Verify services are accessible at configured URLs

### Frontend not loading
- Ensure React was built: `npm run build` in `ui/` folder
- Check that `ui/dist/` exists before building executable
- Verify backend is running: `http://localhost:8787`

### Services showing "Disabled"
- Check service toggle in Settings page
- Verify service URL and API key are correct
- Check logs for connection errors

### Logs not appearing
- Verify write permissions in application directory
- Check that `logs/` directory exists and is writable

## Release Checklist

- [ ] Frontend built with `npm run build`
- [ ] All dependencies in `requirements.txt` installed
- [ ] `config.ini` template updated with documentation
- [ ] PyInstaller spec verified to include all assets
- [ ] Executable tested on clean Windows machine
- [ ] NSIS installer created and tested
- [ ] Version numbers updated in code and installer
- [ ] Git commit and tag created for release

## Performance Notes

- Parallel service checks: ~30-35 seconds maximum response time
- Eligible items fetch: Concurrent with all services
- Page refresh: 1 second delay after operations
- Log persistence: Real-time disk writes
- Frontend: Optimized React build with assets fingerprinting

## Support

For issues, check:
1. `logs/YYYY-MM-DD.txt` for error details
2. Browser console for frontend errors (F12)
3. Verify all *arr services are running and accessible
4. Ensure firewall allows local connections on port 8787

