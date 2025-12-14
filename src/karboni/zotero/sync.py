# ruff: noqa: ERA001, E501, RUF100

import datetime
import logging
from collections.abc import Iterable, Iterator, Sequence
from itertools import chain, islice
from typing import Any, TypeVar

import httpx
from anyio import Path, create_task_group, sleep

from karboni.async_utils import RequestLimiter, stream_result
from karboni.database.library import Library
from karboni.exceptions import (
    BatchSizeError,
    FileAlreadyInSyncError,
    IncrementalSyncInconsistencyError,
    IncrementalSyncStatusError,
    LibraryAlreadyInSyncError,
    LibraryVersionChangeError,
    SkippedError,
    TooManyFailuresError,
)
from karboni.http import make_http_client
from karboni.zotero.config import Config
from karboni.zotero.delta import Delta
from karboni.zotero.handler import (
    BatchHandler,
    CheckApiAccess,
    CheckGroupLibraryAccess,
    CollectionsBatch,
    CollectionsSince,
    DeletedSince,
    FulltextSince,
    Handler,
    ItemFileDownload,
    ItemFulltext,
    ItemsBatch,
    ItemsBibBatch,
    ItemsExportFormatBatch,
    ItemsSince,
    ItemTypeCreatorTypes,
    ItemTypeCreatorTypesLocale,
    ItemTypeFields,
    ItemTypeFieldsLocale,
    ItemTypes,
    ItemTypesLocale,
    SearchesBatch,
    SearchesSince,
    SelectedItemsSince,
)

try:
    from itertools import batched  # Python 3.12+
except ImportError:
    # Fallback for Python < 3.12. CAUTION: Doesn't support the 'strict' arg.
    T = TypeVar("T")

    def batched(iterable: Iterable[T], n: int) -> Iterator[tuple[T, ...]]:  # type: ignore[no-redef]
        it = iter(iterable)
        while batch := tuple(islice(it, n)):
            yield batch


logger = logging.getLogger(__name__)


class Synchronizer:
    """Synchronize data from Zotero into a database."""

    def __init__(
        self,
        database_url: str,
        data_path: Path,
        *,
        locales: list[str] | None = None,
        styles: list[str] | None = None,
        export_formats: list[str] | None = None,
        fulltext: bool = False,
        files: bool = False,
        # TODO: Add option to make searches synchronization optional (but enabled by default)
        media_types: list[str] | None = None,
        **kwargs: Any,
    ):
        """
        Configure the Zotero connection.

        Args:
            database_url: Database connection URL.
            data_path: Path to store files.
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
            media_types: List of accepted media types for file attachments. If None, files are
                         accepted regardless of media type. Ignored if files is False.
            kwargs: Configuration parameters for the Zotero connection.

        Raises:
            ValueError: If a parameter has an invalid value.
        """
        self.database_url = database_url
        self.data_path = data_path
        self.zotero_config = Config(**kwargs)

        # Data options.
        self.locales = list(set(locales or ["en-US"]))  # Going through a set to remove duplicates.
        self.styles = list(set(styles or []))
        self.export_formats = list(set(export_formats or []))
        self.fulltext = fulltext
        self.files = files
        self.media_types = list(set(media_types or []))

        # Variables shared between various methods during synchronization. These
        # are reset on each new synchronize(). Having them as instance variables
        # avoids constantly passing them around as parameters.
        self._delta = Delta()
        self._limiter = RequestLimiter(self.zotero_config.max_concurrent_requests)

    def _init_sync(self, db: Library, full: bool = False) -> None:
        self._delta = Delta(since=0 if full else db.version() or 0)
        self._limiter.reset_concurrency()

        if self._delta.is_incremental_sync():
            logger.info("Mode: incremental synchronization from version %s", self._delta.since)
        else:
            logger.info("Mode: full synchronization")

    async def _check_sync_consistency(self, db: Library, check_data_options: bool = True) -> None:
        """Check for inconsistent synchronization parameters."""
        if self._delta.is_incremental_sync():
            last_sync = db.last_sync()
            if last_sync is None:
                raise IncrementalSyncStatusError

            async def compare(option: str, db_value: Any, current_value: Any) -> None:
                if (
                    not (isinstance(db_value, str) or isinstance(current_value, str))
                    and isinstance(db_value, Sequence)
                    and isinstance(current_value, Sequence)
                ):
                    # Sort sequences before comparison.
                    db_value = sorted(db_value)
                    current_value = sorted(current_value)

                if current_value != db_value:
                    raise IncrementalSyncInconsistencyError(option, db_value, current_value)

            last_data_options = last_sync.get("data_options", {})

            # Using async here not for speed but to check each element independently, and raise all
            # applicable exceptions (not just the first one encountered).
            async with create_task_group() as tg:
                # fmt: off
                tg.start_soon(compare, "library_id", last_sync.get("library_id"), self.zotero_config.library_id)
                tg.start_soon(compare, "library_prefix", last_sync.get("library_prefix"), self.zotero_config.library_prefix)
                if check_data_options:
                    tg.start_soon(compare, "locales", last_data_options.get("locales", []), self.locales)
                    tg.start_soon(compare, "styles", last_data_options.get("styles", []), self.styles)
                    tg.start_soon(compare, "export_formats", last_data_options.get("export_formats", []), self.export_formats)
                    tg.start_soon(compare, "fulltext", last_data_options.get("fulltext"), self.fulltext)
                    tg.start_soon(compare, "files", last_data_options.get("files"), self.files)
                    tg.start_soon(compare, "media_types", last_data_options.get("media_types", []), self.media_types)
                # fmt: on

    def _get_backoff_duration_from_response(self, response: httpx.Response) -> float:
        """
        Determine the wait time before retrying a request based on the HTTP response.

        Check for a backoff or retry-after header in the HTTP response. If not present, apply an
        exponential backoff strategy.

        Returns:
            Number of seconds to wait before retrying, or 0.0 if the response doesn't say.
        """
        if backoff := response.headers.get("Backoff"):
            try:
                return float(backoff)
            except ValueError:
                pass
        if retry_after := response.headers.get("Retry-After"):
            try:
                return float(retry_after)
            except ValueError:
                pass
        return 0.0

    def _get_backoff_duration_from_error_count(self, error_count: int) -> float:
        """
        Determine the wait time before retrying a request based on the number of errors.

        Apply an exponential backoff strategy.

        Returns:
            Number of seconds to wait before retrying.
        """
        return self.zotero_config.initial_retry_wait * error_count

    async def _wait_for_capacity(self, started_backoff: bool) -> None:
        # If we haven't initiated backoff...
        if not started_backoff:
            # ... then wait for an available slot within the concurrency limit.
            await self._limiter.acquire()
        # If we did initiate backoff on the previous iteration, then we can proceed immediately to
        # the request because we have kept our concurrency slot, and have already waited the backoff
        # time when handling the error. As the one that initiated backoff, we're the one that can
        # signal its end, and thus shouldn't be waiting!

    async def _handle_error(
        self,
        exc: httpx.HTTPStatusError,
        error_count: int,
        started_backoff: bool,
        batch_size: int | None = None,
    ) -> bool:
        if error_count >= self.zotero_config.max_errors:
            raise TooManyFailuresError(error_count)

        if exc.response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            self._limiter.reduce_concurrency()

        wait = self._get_backoff_duration_from_response(exc.response)
        if wait == 0.0:
            # No backoff indication from the server response, but we're still dealing with an error.
            # Server errors (5xx) or 429 Too Many Requests deserve a retry.
            if (
                exc.response.is_server_error
                or exc.response.status_code == httpx.codes.TOO_MANY_REQUESTS
            ):
                wait = self._get_backoff_duration_from_error_count(error_count)
            else:
                # Most likely a client error. No backoff needed, just don't retry.
                raise  # noqa: PLE0704

        # If no backoff is currently active.
        if not self._limiter.is_backoff_active():
            if batch_size is not None and batch_size > 1:
                # We're processing a batch whose size can still be reduced; we should cancel all
                # requests from the same batch, reduce batch size, and re-schedule new batches.
                raise BatchSizeError(wait)

            self._limiter.start_backoff()  # We get to start it.
            started_backoff = True

        if started_backoff:
            # We initiated the active backoff, either just now or on a previous attempt,
            # thus we either start waiting, or extend the wait of an already active backoff.
            logger.info("Backing off for %.1f seconds", wait)
            await sleep(wait)  # Wait before retrying.
        else:
            # Give up request slot. Will need to reacquire it at the next try.
            self._limiter.release()

        return started_backoff

    def _make_handler(
        self,
        handler_class: type[Handler],
        db: Library,
        http: httpx.AsyncClient,
        *args: Any,
        **kwargs: Any,
    ) -> Handler:
        """Factory method for creating a request handler with Zotero config and sync delta."""
        return handler_class(self.zotero_config, self._delta, db, http, *args, **kwargs)

    async def _process_request(self, handler: Handler, batch_size: int | None = None) -> Any:
        """Perform a request to the Zotero API with the help of a handler instance."""
        logger.debug("Setup %s", handler)

        result = None
        errors = 0
        started_backoff = False
        try:
            while True:  # Retry loop.
                try:
                    await self._wait_for_capacity(started_backoff)
                    logger.debug("Try #%d %s", errors + 1, handler)

                    response = await handler.request()

                    # Check for error codes in the response.
                    if response.status_code == httpx.codes.NOT_MODIFIED:
                        return handler.empty_result()
                    response.raise_for_status()

                    # Validate and process the response.
                    await handler.validate_response(response)
                    result = await handler.process_response(response)

                    logger.debug("End #%d %s %s", errors + 1, handler, handler.log_result(result))

                except httpx.HTTPStatusError as exc:
                    errors += 1
                    started_backoff = await self._handle_error(
                        exc, errors, started_backoff, batch_size
                    )

                except SkippedError as exc:
                    if isinstance(exc, FileAlreadyInSyncError):
                        logger.debug(exc)
                    else:
                        # Issue deserves a warning, but shouldn't interrupt the sync process.
                        logger.warning(exc)

                    # If we started backoff, signal others the wait is now over.
                    if started_backoff:
                        self._limiter.end_backoff()

                    break  # Break retry loop. Retries wouldn't help.

                else:  # Success!
                    # If we started backoff, signal others the wait is now over.
                    if started_backoff:
                        self._limiter.end_backoff()

                    break  # Break retry loop.
        finally:
            self._limiter.release()

        return result

    async def _process(
        self,
        handler_class: type[Handler],
        db: Library,
        http: httpx.AsyncClient,
        *args: Any,
    ) -> Any:
        """Perform a request to the Zotero API using the specified handler class."""
        return await self._process_request(self._make_handler(handler_class, db, http, *args))

    async def _batch_process(
        self,
        handler_class: type[BatchHandler],
        db: Library,
        http: httpx.AsyncClient,
        keys: list[str],
        *args: Any,
    ) -> None:
        """Request a list of keys from the Zotero API, in batches using the given handler class."""
        logger.debug("Start batch_process %s keys=%d", handler_class.__name__, len(keys))

        stop = False
        batch_size = self.zotero_config.initial_batch_size
        done: list[str] = []
        try:
            while len(done) < len(keys) and not stop:
                try:
                    # Split keys in batches, and process batches concurrently in a nested group. In case
                    # of failure, all concurrent requests get cancelled and smaller batches formed.
                    async with create_task_group() as tg:
                        for batch_num, batch_keys in enumerate(
                            batched([k for k in keys if k not in done], batch_size), start=1
                        ):
                            tg.start_soon(
                                self._process_request,
                                self._make_handler(
                                    handler_class,
                                    db,
                                    http,
                                    batch_num,
                                    batch_size,
                                    batch_keys,
                                    done,
                                    *args,
                                ),
                                batch_size,
                            )

                except* BatchSizeError as exc_group:
                    if batch_size == 1:
                        msg = "Cannot reduce batch size below 1."
                        raise RuntimeError(msg) from exc_group  # Not supposed to happen!
                    wait = max(exc.wait for exc in exc_group.exceptions)  # type: ignore[union-attr]
                    batch_size = max(1, batch_size * 4 // 5)  # Reduce by 20%.
                    logger.info(
                        "Backing off for %.1f seconds in batch_process %s. "
                        "Reducing batch size to %d",
                        wait,
                        handler_class.__name__,
                        batch_size,
                    )
                    # Ideally we'd start backoff to also block other requests not related to this
                    # batch. However, we can't hold a capacity token because we're not sending any
                    # requests, which means sync would be stuck if total capacity is 1. Moreover,
                    # calling start_backoff() while we're not holding any token would still allow 1
                    # request at a time. And trying to acquire a token just for backoff wouldn't
                    # work either because other tasks are likely already ahead in the queue for
                    # getting one and would still be sent before we even start backoff.
                    await sleep(wait)

        except* (
            LibraryAlreadyInSyncError,
            LibraryVersionChangeError,
            TooManyFailuresError,
            IncrementalSyncInconsistencyError,
            httpx.HTTPError,
        ) as exc_group:
            for exc in exc_group.exceptions:
                # Un-nest exception groups.
                if isinstance(exc, ExceptionGroup):
                    for sub_exc in exc.exceptions:
                        raise sub_exc  # noqa: B904
                else:
                    raise exc  # noqa: B904

        logger.debug("End batch_process %s", handler_class.__name__)

    def _make_http_client(self) -> httpx.AsyncClient:
        """Create an HTTP client configured for Zotero API requests."""
        return make_http_client(
            max_connections=self.zotero_config.max_concurrent_requests,
            max_keepalive_connections=max(1, self.zotero_config.max_concurrent_requests // 2),
        )

    async def check(self, full: bool = False) -> None:
        """Check synchronization status of the Zotero library."""
        with Library(self.database_url, readonly=True) as db:
            self._init_sync(db, full)
            if self._delta.is_incremental_sync():
                # Make sure parameters are consistent with previous sync.
                await self._check_sync_consistency(db, check_data_options=False)
            async with self._make_http_client() as http:
                # Check API and library access (sequentially).
                await self._process(CheckApiAccess, db, http)
                if self.zotero_config.library_prefix == "groups":
                    await self._process(CheckGroupLibraryAccess, db, http)

                # Start other getters (concurrently).
                async with create_task_group() as tg:
                    tg.start_soon(self._process, CollectionsSince, db, http)
                    tg.start_soon(self._process, SearchesSince, db, http)
                    tg.start_soon(self._process, ItemsSince, db, http)
                    tg.start_soon(self._process, DeletedSince, db, http)
                    if self.fulltext:
                        tg.start_soon(self._process, FulltextSince, db, http)

                if self._delta.target in [0, self._delta.since]:
                    # Some API calls always return 0 as target when there are no changes.
                    raise LibraryAlreadyInSyncError

                logger.info(
                    "Synchronization required to update to Zotero library version %s",
                    self._delta.target,
                )

    async def synchronize(self, full: bool = False) -> None:
        """Perform a full synchronization of the Zotero library into the database."""
        started_on = datetime.datetime.now(datetime.UTC)
        with Library(self.database_url) as db:
            self._init_sync(db, full)
            if self._delta.is_incremental_sync():
                # Make sure parameters are consistent with previous sync.
                await self._check_sync_consistency(db)
            else:
                # Make sure database is empty before full sync.
                db.delete_all()

            async with self._make_http_client() as http:
                # Apply the sync process described here:
                # https://www.zotero.org/support/dev/web_api/v3/syncing

                # Check API and library access (sequentially).
                await self._process(CheckApiAccess, db, http)
                if self.zotero_config.library_prefix == "groups":
                    await self._process(CheckGroupLibraryAccess, db, http)

                # Create getters and their output streams.
                # fmt: off
                item_types_update, item_types_stream = stream_result(self._process)(ItemTypes, db, http)
                collections_since, collections_stream = stream_result(self._process)(CollectionsSince, db, http)
                searches_since, searches_stream = stream_result(self._process)(SearchesSince, db, http)
                items_since, items_stream = stream_result(self._process)(ItemsSince, db, http)
                deleted_since, deleted_stream = stream_result(self._process)(DeletedSince, db, http)
                fulltext_since, fulltext_stream = stream_result(self._process)(FulltextSince, db, http)
                # fmt: on

                async with create_task_group() as tg:
                    # Get item types and update them in database.
                    tg.start_soon(item_types_update)

                    # Start other getters (concurrently).
                    tg.start_soon(collections_since)
                    tg.start_soon(searches_since)
                    tg.start_soon(items_since)
                    tg.start_soon(deleted_since)
                    if self.fulltext:
                        tg.start_soon(fulltext_since)

                    # Collect getter results from streams.
                    item_types = await item_types_stream.receive()  # noqa: F841
                    collection_keys = await collections_stream.receive()  # noqa: F841
                    search_keys = await searches_stream.receive()  # noqa: F841
                    item_keys = await items_stream.receive()  # noqa: F841
                    deleted_objects = await deleted_stream.receive()  # noqa: F841
                    if self.fulltext:
                        fulltext_item_keys = await fulltext_stream.receive()  # noqa: F841
                    else:
                        fulltext_item_keys = []

                    if collection_keys:
                        # Update collections in database.
                        tg.start_soon(
                            self._batch_process, CollectionsBatch, db, http, collection_keys
                        )

                    if search_keys:
                        # Update searches in database.
                        tg.start_soon(self._batch_process, SearchesBatch, db, http, search_keys)

                logger.debug("Task group 1 completed")

                # Check if there are actual changes to the library.
                if not (
                    collection_keys
                    or item_keys
                    or search_keys
                    or fulltext_item_keys
                    or deleted_objects.get("items")
                    or deleted_objects.get("collections")
                    or deleted_objects.get("searches")
                    or (self.files and db.files_to_download(self.media_types))
                    or (self.files and db.files_to_delete())
                ):
                    raise LibraryAlreadyInSyncError

                # Create getter and its output stream for items that are actual bibliographic
                # references and not trashed. This output will determine which formatted references
                # and export formats will be fetched because, e.g., we don't need to formatted
                # references for notes or trashed items.
                # fmt: off
                ref_item_types = [t for t in item_types if t not in ("note", "attachment", "annotation")]
                ref_items_since, ref_items_stream = stream_result(self._process)(SelectedItemsSince, db, http, ref_item_types)
                # fmt: on

                async with create_task_group() as tg:
                    if item_types:
                        # Update item types in database. The Zotero API doesn't apply versioning to
                        # item types, thus we systematically update them whenever the library has
                        # changes. Because we haven't established foreign key relationships between
                        # items and item types, we can update them concurrently.
                        for locale in self.locales:
                            tg.start_soon(self._process, ItemTypesLocale, db, http, locale)
                        for item_type in item_types:
                            tg.start_soon(self._process, ItemTypeFields, db, http, item_type)
                            tg.start_soon(self._process, ItemTypeCreatorTypes, db, http, item_type)
                            for locale in self.locales:
                                # fmt: off
                                tg.start_soon(self._process, ItemTypeFieldsLocale, db, http, item_type, locale)
                                tg.start_soon(self._process, ItemTypeCreatorTypesLocale, db, http, item_type, locale)
                                # fmt: on

                    if self.styles or self.export_formats:
                        # Get items that are actual references and not trashed.
                        tg.start_soon(ref_items_since)

                    if item_keys:
                        # Update items in database. To ensure integrity of foreign key relations, we
                        # process items only after collections have been fully synchronized. Hence
                        # the consecutive task group.
                        tg.start_soon(self._batch_process, ItemsBatch, db, http, item_keys)

                    if self.styles or self.export_formats:
                        ref_item_keys = await ref_items_stream.receive()  # noqa: F841
                    else:
                        ref_item_keys = []

                logger.debug("Task group 2 completed")

                # To ensure integrity of foreign key relations, we process item-related tables only
                # after the items have been synchronized.
                async with create_task_group() as tg:
                    if ref_item_keys:
                        # Although the Zotero API can fetch item data, a bibliographic style, and
                        # multiple export formats in a single request, in practice it seems to make
                        # the requests more resource intensive and more likely to cause a server
                        # error. By using separate requests for each type of output, we use less
                        # resources per request and reduce the risk of failure.

                        # fmt: off
                        # Update formatted references in database.
                        for style in self.styles:
                            for locale in self.locales:
                                tg.start_soon(self._batch_process, ItemsBibBatch, db, http, ref_item_keys, style, locale)

                        # Update export formats in database.
                        for export_format in self.export_formats:
                            tg.start_soon(self._batch_process, ItemsExportFormatBatch, db, http, ref_item_keys, export_format)
                        # fmt: on

                    if fulltext_item_keys:
                        for item_key in fulltext_item_keys:
                            tg.start_soon(self._process, ItemFulltext, db, http, item_key)

                logger.debug("Task group 3 completed")

            # Delete items, collections, and searches that Zotero says have been permanently
            # deleted. We don't know anything about those except their keys. We delete them if they
            # exist, cascading to dependent tables.
            if deleted_items := deleted_objects.get("items", []):
                # Store keys of deleted items.
                db.insert_deleted_items(deleted_items)
                # Delete the items.
                logger.debug("Deleting %d item(s)", len(deleted_items))
                db.bulk_delete_items(deleted_items)
            if deleted_collections := deleted_objects.get("collections", []):
                # The Zotero API doesn't report deleted subcollections, thus we must find them, if
                # any, and add them to our deletion list.
                deleted_collections = chain(
                    deleted_collections,
                    *[db.find_subcollection(key) for key in deleted_collections],
                )
                deleted_collections = list(set(deleted_collections))  # Remove potential duplicates.
                # Store keys of deleted collections.
                db.insert_deleted_collections(deleted_collections)
                # Delete the collections.
                logger.debug("Deleting %d collection(s)", len(deleted_collections))
                db.bulk_delete_collections(deleted_collections)
            if deleted_searches := deleted_objects.get("searches", []):
                # Store keys of deleted searches.
                db.insert_deleted_searches(deleted_searches)
                # Delete the searches.
                logger.debug("Deleting %d search(es)", len(deleted_searches))
                db.bulk_delete_searches(deleted_searches)

            # Add synchronization history entry.
            history_id = db.insert_sync_history(
                library_id=self.zotero_config.library_id,
                library_prefix=self.zotero_config.library_prefix,
                since_version=self._delta.since,
                to_version=self._delta.target,
                started_on=started_on,
                ended_on=datetime.datetime.now(datetime.UTC),
                data_options={
                    "locales": self.locales,
                    "styles": self.styles,
                    "export_formats": self.export_formats,
                    "fulltext": self.fulltext,
                    "files": self.files,
                    "media_types": self.media_types,
                },
                process_options={
                    "initial-batch-size": self.zotero_config.initial_batch_size,
                    "initial-retry-wait": self.zotero_config.initial_retry_wait,
                    "max-concurrent-requests": self.zotero_config.max_concurrent_requests,
                    "max-errors": self.zotero_config.max_errors,
                },
                updated_item_count=len(item_keys),
                updated_item_fulltext_count=len(fulltext_item_keys),
                updated_collection_count=len(collection_keys),
                updated_search_count=len(search_keys),
                deleted_item_count=len(deleted_items),
                deleted_collection_count=len(deleted_collections),
                deleted_search_count=len(deleted_searches),
            )

        if self.files:
            # Update file attachments. This will perform a separate database transaction because we
            # want the library to sync even if there are issues with synchronizing the files. File
            # sync isn't atomic, thus failure might leave the files in an inconsistent state.
            await self._synchronize_files(history_id, deleted_objects.get("items", []))

    async def _synchronize_files(self, history_id: int, deleted_items: list[str]) -> None:
        """
        Synchronize file attachments.

        Args:
            history_id: ID of the sync history entry for the current sync.
            deleted_items: List of items that Zotero says have been permanently deleted. We don't
                           know anything about those items except their keys, thus we don't know
                           whether they were attachments or not, but we'll delete matching files if
                           any are found.
        """
        started_on = datetime.datetime.now(datetime.UTC)

        logger.debug("Start updating file attachments")

        dest_dir = self.data_path / "attachments"
        await dest_dir.mkdir(parents=True, exist_ok=True)

        with Library(self.database_url) as db:
            async with self._make_http_client() as http:  # noqa: SIM117
                async with create_task_group() as tg:
                    # Download attachments that have status "unknown" or "error".
                    files_to_download = db.files_to_download(self.media_types)
                    for item_file in files_to_download:
                        tg.start_soon(
                            self._process,
                            ItemFileDownload,
                            db,
                            http,
                            dest_dir,
                            item_file,
                        )

                    # Delete files matching trashed or permanently deleted items.
                    files_to_delete = set(deleted_items + db.files_to_delete())
                    for item_key in files_to_delete:
                        tg.start_soon(self._delete_file, db, dest_dir, item_key)

                    # TODO: Delete dangling files, i.e., any file on disk that's not in the ItemFile table?

                logger.debug("Task group 4 completed")

            db.update_sync_history(
                history_id,
                files_started_on=started_on,
                files_ended_on=datetime.datetime.now(datetime.UTC),
                updated_file_count=len(files_to_download),
                deleted_file_count=len(files_to_delete),
            )

    @staticmethod
    async def _delete_file(db: Library, dest_dir: Path, item_key: str) -> None:
        file_path = dest_dir / item_key
        if await file_path.exists():
            try:
                await file_path.unlink()

                logger.debug("Deleted file attachment: %s", file_path)
                db.update_item_file_download_status(
                    item_key,
                    db.FILE_DOWNLOAD_STATUS_DELETED,
                )

            except OSError as exc:
                logger.warning("Failed to delete file attachment: %s. %s", file_path, exc)
                db.update_item_file_download_status(
                    item_key,
                    db.FILE_DOWNLOAD_STATUS_ERROR,
                )
        else:
            # The item might not even have been an attachment, but if its key is present in the
            # ItemFile table, mark the file as deleted.
            db.update_item_file_download_status(
                item_key,
                db.FILE_DOWNLOAD_STATUS_DELETED,
            )
