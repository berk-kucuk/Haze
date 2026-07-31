"""
Lightweight file logging for diagnosing connection / message-delivery issues.

Writes to a rotating log under the user's XDG state dir (falls back to /tmp).
Set HAZE_LOG=<path> to override the location.

PRIVACY: this file outlives the session, so what reaches it is deliberately
limited. The file handler records warnings and errors only — enough to explain
a crash or a failed connection — unless HAZE_DEBUG=1 asks for the full trace.
Identifiers that would reconstruct who you talked to (onion addresses,
nicknames) go through `redact()` first, and `wipe_logs()` deletes the files
outright on the panic path.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "haze"
_configured = False
_log_paths: list[Path] = []


def redact(value: str | None) -> str:
    """Shorten an identifier so a log line stays diagnosable but not revealing.

    An onion address or nickname in a log file is a record of who someone
    talked to, kept long after the session it belonged to. Only a short prefix
    survives — enough to correlate two lines in the same run, not enough to
    identify the peer or look the service up.
    """
    if not value:
        return "-"
    text = str(value)
    return f"{text[:4]}…({len(text)})"


def _default_log_path() -> Path:
    override = os.environ.get("HAZE_LOG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = Path(base) / "haze"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d / "haze.log"
    except Exception:
        return Path("/tmp/haze.log")


def setup_logging() -> Path:
    """Configure the 'haze' logger once. Returns the log file path."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return Path(getattr(logger, "_haze_path", _default_log_path()))

    # Debug output is opt-in rather than opt-out: the default file log keeps
    # warnings and errors (so a crash is still explainable) but not the
    # routine per-connection/per-event chatter that turns the file into a
    # session history.
    debug = os.environ.get("HAZE_DEBUG") == "1"
    logger.setLevel(logging.DEBUG if debug else logging.WARNING)
    path = _default_log_path()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            datefmt="%H:%M:%S")
    try:
        fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG if debug else logging.WARNING)
        logger.addHandler(fh)
        _log_paths.clear()
        _log_paths.append(path)
        # RotatingFileHandler keeps haze.log.1 / haze.log.2 alongside it.
        _log_paths.extend(Path(f"{path}.{i}") for i in range(1, 3))
    except Exception:
        pass
    # Also mirror to stderr so `haze` run from a terminal shows live logs.
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    logger._haze_path = str(path)  # type: ignore[attr-defined]
    _configured = True
    return path


def get_logger(name: str = "") -> logging.Logger:
    base = logging.getLogger(_LOGGER_NAME)
    return base.getChild(name) if name else base


def wipe_logs() -> None:
    """Detach the file handlers and delete the log files, including rotations.

    Called from the panic path. A panic wipe that clears messages and the
    hidden service but leaves a file recording when the app ran — and, before
    this, which onion addresses it connected to — hands an examiner exactly the
    trail the button exists to destroy.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)
    for path in _log_paths:
        try:
            if path.exists():
                # Overwrite before unlinking: a plain delete leaves the content
                # in place until the blocks are reused.
                size = path.stat().st_size
                with open(path, "r+b", buffering=0) as f:
                    f.write(b"\x00" * size)
                    f.flush()
                    os.fsync(f.fileno())
                path.unlink()
        except Exception:
            pass
    _log_paths.clear()
