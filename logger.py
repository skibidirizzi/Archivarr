"""
Logging module matching *arr app logging format and style.

Format: [HH:MM:SS] LEVEL [Component] Message
Example: [14:32:10] Info [Lidarr] Scanning for artists...

Real-time logging: Logs are continuously written to disk as they're generated,
matching the behavior of Radarr, Sonarr, and Lidarr. Each log line is appended
to a daily log file immediately upon creation.
"""

import time
from enum import Enum
from pathlib import Path
from typing import List, Optional


class LogLevel(Enum):
    """Log levels matching *arr standards."""
    DEBUG = "Debug"
    INFO = "Info"
    WARN = "Warn"
    ERROR = "Error"


class Logger:
    """
    Logger instance for a specific component/module.
    Matches the logging style of Radarr, Sonarr, and Lidarr.
    
    Logs can be written to:
    - In-memory list (for API responses)
    - Disk (for persistent storage)
    - Both simultaneously
    """

    def __init__(
        self,
        component: str,
        log_list: Optional[List[str]] = None,
        log_file: Optional[Path] = None
    ):
        """
        Initialize logger for a component.

        Args:
            component: Component/module name (e.g., "Lidarr", "Archive", "Server")
            log_list: Optional list to append log entries to (for in-memory logging)
            log_file: Optional file path to write logs to (for persistent logging)
        """
        self.component = component
        self.log_list = log_list if log_list is not None else []
        self.log_file = log_file
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _format_entry(self, level: LogLevel, message: str) -> str:
        """Format a log entry in *arr style."""
        timestamp = time.strftime("%H:%M:%S")
        return f"[{timestamp}] {level.value} [{self.component}] {message}"

    def _write_entry(self, entry: str) -> None:
        """Write entry to both in-memory list and disk file."""
        self.log_list.append(entry)
        if self.log_file:
            try:
                # Ensure parent directory exists
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                # Append to file
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception as e:
                # Print errors so they're visible in console
                error_msg = f"Failed to write to log file {self.log_file}: {e}"
                print(error_msg, flush=True)
                # Still append to in-memory list so API works
                self.log_list.append(f"[LOG ERROR] {error_msg}")

    def debug(self, message: str) -> None:
        """Log debug message."""
        entry = self._format_entry(LogLevel.DEBUG, message)
        self._write_entry(entry)

    def info(self, message: str) -> None:
        """Log info message."""
        entry = self._format_entry(LogLevel.INFO, message)
        self._write_entry(entry)

    def warn(self, message: str) -> None:
        """Log warning message."""
        entry = self._format_entry(LogLevel.WARN, message)
        self._write_entry(entry)

    def error(self, message: str) -> None:
        """Log error message."""
        entry = self._format_entry(LogLevel.ERROR, message)
        self._write_entry(entry)


def create_logger(
    component: str,
    log_list: Optional[List[str]] = None,
    log_file: Optional[Path] = None
) -> Logger:
    """Factory function to create a logger instance."""
    return Logger(component, log_list, log_file)


def save_logs_to_file(logs: List[str], log_dir: Path) -> None:
    """
    Save run logs to disk for historical access.
    
    Note: With real-time logging, this function is primarily used for
    legacy compatibility or batch appending. Most logs should be written
    immediately by the Logger instance.
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        log_path = log_dir / f"{today}.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            for entry in logs:
                f.write(entry + "\n")
    except Exception as e:
        print(f"Failed to save logs: {e}")
