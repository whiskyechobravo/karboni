"""Main operations for managing the mirror database."""

import logging
from pathlib import Path
from typing import Any

import httpx
from anyio import Path as AsyncPath
from anyio import run

from karboni.database.engine import create_engine
from karboni.database.schema import Base
from karboni.exceptions import LibraryAlreadyInSyncError, SyncError, UsageError
from karboni.utils import format_response
from karboni.zotero.sync import Synchronizer

logger = logging.getLogger(__name__)


def initialize(database_url: str) -> None:
    """Initialize the mirror database."""
    try:
        engine = create_engine(database_url)
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def clean(database_url: str, data_path: Path, files: bool = False) -> None:
    """
    Clear the mirror database.

    Args:
        database_url: Connection URL for the mirror database.
        data_path: Path to store files.
        files: Whether to delete the file attachments locally. Defaults to False.
    """
    try:
        engine = create_engine(database_url)
        Base.metadata.drop_all(engine)

        if files:
            attachments_path = data_path / "attachments"
            if attachments_path.exists() and attachments_path.is_dir():
                for file_path in attachments_path.iterdir():
                    if file_path.is_file():
                        try:
                            file_path.unlink()
                        except OSError as exc:
                            logger.warning(
                                "Failed to delete file attachment: %s. %s", file_path.name, exc
                            )
    finally:
        engine.dispose()


async def _async_execute(
    operation: str,
    database_url: str,
    data_path: AsyncPath,
    library_id: str,
    library_prefix: str,
    api_key: str,
    options: dict[str, Any],
) -> bool:
    """Perform an asynchronous process to synchronize the Zotero library."""
    success = True

    # TODO: Verify that the database has been initialized and has the correct schema.

    try:
        full = options.pop("full", False)
        synchronizer = Synchronizer(
            database_url=database_url,
            data_path=data_path,
            library_id=library_id,
            library_prefix=library_prefix,
            api_key=api_key,
            **options,
        )
        await getattr(synchronizer, operation)(full)

    except* (SyncError, UsageError) as exc_group:
        for exc in exc_group.exceptions:
            if isinstance(exc, LibraryAlreadyInSyncError):
                logger.info(exc)
            else:
                logger.error(exc)  # noqa: TRY400 (No traceback wanted)
                success = False

    except* httpx.HTTPError as exc_group:
        for http_exc in exc_group.exceptions:
            logger.error(http_exc)  # noqa: TRY400
            if logger.isEnabledFor(logging.DEBUG) and isinstance(http_exc, httpx.HTTPStatusError):
                logger.debug("%s", format_response(http_exc.response))
        success = False

    return success


def synchronize(  # noqa: D417
    database_url: str,
    data_path: Path,
    library_id: str,
    library_prefix: str,
    api_key: str,
    **kwargs: Any,
) -> bool:
    """
    Synchronize the Zotero library.

    Args:
        database_url: Connection URL for the mirror database.
        data_path: Path to store files.
        library_id: UserID or GroupID of the Zotero library.
        library_prefix: Either "users" or "groups" depending on the type of library.
        api_key: Zotero API key for accessing the library.
        initial_batch_size: Number objects to fetch by key in a single request.
        initial_retry_wait: Initial wait time (in seconds) for exponential backoff calculation.
        max_concurrent_requests: Maximum number of concurrent API requests at any given time.
        max_errors: Maximum number of attempts a given API request is allowed.
        full: Force a full synchronization. Defaults to False.
        locales: List of desired locales for labels or to apply to reference formatting.
                 Defaults to ["en-US"].
        styles: List of bibliographic styles to format references with (see
                https://www.zotero.org/support/dev/web_api/v3/basics#parameters_for_format_bib_includecontent_bib_includecontent_citation).
                Defaults to None.
        export_formats: List of export formats to retrieve (see
                        https://www.zotero.org/support/dev/web_api/v3/basics#item_export_formats).
                        Defaults to None.
        fulltext: Whether to fetch the full text content (if any) of items. Defaults to False.
        files: Whether to fetch file attachments (if any). Defaults to False.
        media_types: List of accepted media types for file attachments. If None, files are accepted
                     regardless of media type. Ignored if files is False.
    """
    # Note: kwargs not unpacked because run() only accepts positional arguments.
    return run(
        _async_execute,
        "synchronize",
        database_url,
        AsyncPath(data_path),
        library_id,
        library_prefix,
        api_key,
        kwargs,
    )


def check(  # noqa: D417
    database_url: str,
    data_path: Path,
    library_id: str,
    library_prefix: str,
    api_key: str,
    **kwargs: Any,
) -> bool:
    """
    Check synchronization status of the Zotero library.

    Args:
        database_url: Connection URL for the mirror database.
        data_path: Path to store files.
        library_id: UserID or GroupID of the Zotero library.
        library_prefix: Either "users" or "groups" depending on the type of library.
        api_key: Zotero API key for accessing the library.
        initial_batch_size: Number objects to fetch by key in a single request.
        initial_retry_wait: Initial wait time (in seconds) for exponential backoff calculation.
        max_concurrent_requests: Maximum number of concurrent API requests at any given time.
        max_errors: Maximum number of attempts a given API request is allowed.
        full: Force a full synchronization. Defaults to False.
        locales: List of desired locales for labels or to apply to reference formatting.
                 Defaults to ["en-US"].
        styles: List of bibliographic styles to format references with (see
                https://www.zotero.org/support/dev/web_api/v3/basics#parameters_for_format_bib_includecontent_bib_includecontent_citation).
                Defaults to None.
        export_formats: List of export formats to retrieve (see
                        https://www.zotero.org/support/dev/web_api/v3/basics#item_export_formats).
                        Defaults to None.
        fulltext: Whether to fetch the full text content (if any) of items. Defaults to False.
        files: Whether to fetch file attachments (if any). Defaults to False.
        media_types: List of accepted media types for file attachments. If None, files are accepted
                     regardless of media type. Ignored if files is False.
    """
    # Note: kwargs not unpacked because run() only accepts positional arguments.
    return run(
        _async_execute,
        "check",
        database_url,
        AsyncPath(data_path),
        library_id,
        library_prefix,
        api_key,
        kwargs,
    )
