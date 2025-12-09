from typing import Annotated

from karboni import __version__
from karboni.exceptions import LibraryPrefixError
from karboni.typing import Range, validate_range_annotations


class Config:
    """Stores the basic connections details for Zotero API requests."""

    def __init__(
        self,
        *,
        library_id: str,
        library_prefix: str,
        api_key: str,
        base_url: str = "",
        initial_batch_size: Annotated[int, Range(1, 50)] = 50,
        initial_retry_wait: Annotated[float, Range(1.0, 600.0)] = 2.0,
        max_concurrent_requests: Annotated[int, Range(1, 50)] = 20,
        max_errors: Annotated[int, Range(1, 25)] = 10,
    ):
        """
        Initialize Zotero configuration.

        Args:
            library_id: UserID or GroupID of the Zotero library.
            library_prefix: Either "users" or "groups" depending on the type of library.
            api_key: Zotero API key for accessing the library.
            base_url: Base URL for API requests. Defaults to "https://api.zotero.org".
            initial_batch_size: Number objects to fetch by key in a single request.
            initial_retry_wait: Initial wait time (in seconds) for exponential backoff calculation.
            max_concurrent_requests: Maximum number of concurrent API requests at any given time.
            max_errors: Maximum number of attempts a given API request is allowed.
        """
        validate_range_annotations(
            Config.__init__,
            initial_batch_size=initial_batch_size,
            initial_retry_wait=initial_retry_wait,
            max_concurrent_requests=max_concurrent_requests,
            max_errors=max_errors,
        )

        if library_prefix not in ["users", "groups"]:
            raise LibraryPrefixError
        self.library_id = library_id
        self.library_prefix = library_prefix
        self.api_key = api_key
        self.base_url = base_url or "https://api.zotero.org"
        self.base_headers = {
            "Zotero-API-Version": "3",
            "Zotero-API-Key": api_key,
            "User-Agent": f"karboni/{__version__}",
        }
        self.initial_batch_size = initial_batch_size
        self.initial_retry_wait = initial_retry_wait
        self.max_concurrent_requests = max_concurrent_requests
        self.max_errors = max_errors
