"""Validate local launcher destinations before publishing panel configuration."""

import re
from urllib.parse import unquote, urljoin, urlsplit

from .const import DEFAULT_HOME_PATH


def validate_home_path(value: str) -> str:
    """Accept an origin-relative path, never a host, credentials, or URL scheme."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise ValueError("Use a local path beginning with one slash")
    decoded = unquote(value, errors="strict")
    if (
        decoded.startswith("//")
        or re.search(r"%(?![0-9a-fA-F]{2})", value)
        or "\\" in decoded
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in decoded)
        or any(part in (".", "..") for part in urlsplit(decoded).path.split("/"))
    ):
        raise ValueError("Invalid local launcher path")
    target = urlsplit(urljoin("https://glowbright.invalid", value))
    if target.scheme != "https" or target.netloc != "glowbright.invalid":
        raise ValueError("Launcher must remain on the Home Assistant origin")
    return value


def home_path_or_default(value: str) -> str:
    """Handle legacy or manually edited options without breaking panel setup."""
    try:
        return validate_home_path(value)
    except ValueError, UnicodeError:
        return DEFAULT_HOME_PATH
