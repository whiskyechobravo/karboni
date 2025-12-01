"""Karboni: Mirror a Zotero library into a SQL database."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version(__package__ or __name__)
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

# Import and expose main functions from database module
from .database import check, clean, initialize, synchronize

__all__ = ["__version__", "check", "clean", "initialize", "synchronize"]
