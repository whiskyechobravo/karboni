import hashlib
import logging
import os
import zipfile
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any

import httpx
from anyio import Path

from karboni.database.library import Library
from karboni.exceptions import (
    SkippedFileAlreadyInSyncError,
    SkippedFileDecompressionError,
    SkippedFileIntegrityError,
    SkippedFileWriteError,
)
from karboni.zotero.config import Config
from karboni.zotero.delta import Delta

logger = logging.getLogger(__name__)


class Handler(ABC):
    """Build and process a request."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
    ) -> None:
        self.zotero_config = zotero_config
        self.delta = delta
        self.db = db
        self.http = http

    @property
    def headers(self) -> dict[str, Any]:
        """Return the headers to use for the request."""
        return self.zotero_config.base_headers

    @property
    @abstractmethod
    def url(self) -> str:
        """Return the URL to use for the request."""

    async def request(self) -> httpx.Response:
        """
        Perform the HTTP request and return the response.

        Raises:
            httpx.HTTPError: Raised if an HTTP error occurs.
            RequestSkippedError: Raised if the request is skipped for some reason.
        """
        return await self.http.get(self.url, headers=self.headers)

    async def validate_response(self, response: httpx.Response) -> None:  # noqa: B027
        """
        Perform request-specific validation.

        Raises an exception if the response is not valid. By default does nothing.
        """

    @abstractmethod
    async def process_response(self, response: httpx.Response) -> Any:
        """
        Process the response and (perhaps) return a result.

        A handler may choose to not return any result but instead save data to the database.
        """

    def empty_result(self) -> Any:
        """Return an empty result of the appropriate type."""
        return None  # Fine for most handlers (most don't return a result but save to db).

    def __str__(self) -> str:
        return self.__class__.__name__

    def log_result(self, result: Any) -> str:  # noqa: ARG002
        """Format log details based on the given result."""
        return ""  # Fine for most handlers (most don't return a result but save to db).


class CheckApiAccess(Handler):
    """
    Check access to the Zotero API.

    Doesn't do anything but log messages. If the API can't be accessed, the
    request will result in an HTTP error code.
    """

    @property
    def url(self) -> str:
        return f"{self.zotero_config.base_url}/keys/current"

    async def process_response(self, response: httpx.Response) -> None:
        logger.info(
            "Zotero API key owned by: %s (Username: %s; User ID: %s)",
            response.json().get("displayName"),
            response.json().get("username"),
            response.json().get("userID"),
        )


class CheckGroupLibraryAccess(Handler):
    """
    Check access to a Zotero group library.

    Doesn't do anything but log messages. If the library can't be accessed, the
    request will result in an HTTP error code.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        logger.info(
            "Zotero group library: %s (Group ID: %s)",
            response.json().get("data", {}).get("name"),
            self.zotero_config.library_id,
        )


class SinceHandler(Handler, ABC):
    @property
    def headers(self) -> dict[str, Any]:
        return {
            **self.zotero_config.base_headers,
            "If-Modified-Since-Version": str(self.delta.since),
        }

    def _check_version_change(self, response: httpx.Response) -> None:
        """
        Check if the library version has changed during synchronization.

        Raises:
            VersionChangeError: Raised if the last-modified-version found in the response headers
                                differs from last check.
        """
        try:
            last_modified_version = int(response.headers.get("Last-Modified-Version", 0))
        except ValueError:
            last_modified_version = 0
        self.delta.update_target(last_modified_version)

    async def validate_response(self, response: httpx.Response) -> None:
        self._check_version_change(response)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} since={self.delta.since} to={self.delta.target}"


class KeysSinceHandler(SinceHandler, ABC):
    """Base class for handlers that return object keys."""

    async def process_response(self, response: httpx.Response) -> list[str]:
        return await self._filter_since(response.json())

    def empty_result(self) -> list[str]:
        return []

    def log_result(self, result: list[str]) -> str:
        return f"→ {len(result)} key(s)"

    async def _filter_since(self, objects: dict[str, int]) -> list[str]:
        """
        Filter out objects to keep only those that are newer than 'since'.

        Args:
            objects: Dictionary of object keys and their versions.

        Returns:
            List of object keys that have a version greater than 'since'.
        """
        return [key for key, version in objects.items() if version > self.delta.since]


class ItemTypes(SinceHandler):
    """Update item types and return the list of item type identifiers."""

    @property
    def url(self) -> str:
        return f"{self.zotero_config.base_url}/itemTypes?since={self.delta.since}"

    async def process_response(self, response: httpx.Response) -> list[str]:
        data = response.json()
        self.db.update_item_types(data)
        return [t["itemType"] for t in data]

    def empty_result(self) -> list[str]:
        return []

    def log_result(self, result: list[str]) -> str:
        return f"→ {len(result)} item type(s)"


class ItemTypesLocale(SinceHandler):
    """Update item types for a specific locale."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        locale: str,
    ):
        self.locale = locale
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/itemTypes?since={self.delta.since}&locale={self.locale}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_types_locale(response.json(), self.locale)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} locale={self.locale}"


class ItemTypeFields(SinceHandler):
    """Update fields for a specific item type."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_type: str,
    ):
        self.item_type = item_type
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/itemTypeFields"
            f"?since={self.delta.since}&itemType={self.item_type}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_type_fields(response.json(), self.item_type)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_type={self.item_type}"


class ItemTypeFieldsLocale(SinceHandler):
    """Update fields for a specific item type and locale."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_type: str,
        locale: str,
    ):
        self.item_type = item_type
        self.locale = locale
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/itemTypeFields"
            f"?since={self.delta.since}&itemType={self.item_type}&locale={self.locale}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_type_fields_locale(response.json(), self.item_type, self.locale)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_type={self.item_type} locale={self.locale}"


class ItemTypeCreatorTypes(SinceHandler):
    """Update creator types for a specific item type."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_type: str,
    ):
        self.item_type = item_type
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/itemTypeCreatorTypes"
            f"?since={self.delta.since}&itemType={self.item_type}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_type_creator_types(response.json(), self.item_type)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_type={self.item_type}"


class ItemTypeCreatorTypesLocale(SinceHandler):
    """Update creator types for a specific item type and locale."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_type: str,
        locale: str,
    ):
        self.item_type = item_type
        self.locale = locale
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/itemTypeCreatorTypes"
            f"?since={self.delta.since}&itemType={self.item_type}&locale={self.locale}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_type_creator_types_locale(response.json(), self.item_type, self.locale)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_type={self.item_type} locale={self.locale}"


class CollectionsSince(KeysSinceHandler):
    """
    Get the keys of collections that have been added or modified after the 'since' version.

    Trashed collections are included in the response.

    The Zotero API puts no count limit when retrieving just the keys, thus all keys are fetched
    in a single request.

    This handler doesn't change anything in the database.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/collections"
            f"?since={self.delta.since}&format=versions"
        )


class SearchesSince(KeysSinceHandler):
    """
    Get the keys of searches that have been added or modified after the 'since' version.

    Trashed searches are included in the response.

    The Zotero API puts no count limit when retrieving just the keys, thus all keys are fetched
    in a single request.

    This handler doesn't change anything in the database.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/searches"
            f"?since={self.delta.since}&format=versions"
        )


class ItemsSince(KeysSinceHandler):
    """
    Get the keys of items that have been added or modified after the 'since' version.

    Trashed items are included in the response.

    The Zotero API puts no count limit when retrieving just the keys, thus all keys are fetched
    in a single request.

    This handler doesn't change anything in the database.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items"
            f"?since={self.delta.since}&format=versions&includeTrashed=1"
        )


class SelectedItemsSince(KeysSinceHandler):
    """
    Get the keys of selected items that have been added or modified after 'since'.

    Selected items are top-level (no parent), non-trashed, and have a match in the specified list of
    item types.

    The Zotero API puts no count limit when retrieving just the keys, thus all keys are fetched in a
    single request.

    This handler doesn't change anything in the database.
    """

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_types: list[str],
    ):
        self.item_types = item_types
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items/top"
            f"?since={self.delta.since}&format=versions"
            f"&itemType={' || '.join(self.item_types)}"
        )


class DeletedSince(SinceHandler):
    """
    Get the keys of objects that have been permanently deleted after the 'since' version.

    This handler doesn't change anything in the database.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/deleted?since={self.delta.since}"
        )

    async def process_response(self, response: httpx.Response) -> dict[str, list[str]]:
        return response.json()  # type: ignore[no-any-return]

    def empty_result(self) -> dict[str, list[str]]:
        return {"collections": [], "items": [], "searches": []}

    def log_result(self, result: dict[str, list[str]]) -> str:
        return (
            f"→ {len(result['items'])} items(s), "
            f"{len(result['collections'])} collections(s), "
            f"{len(result['searches'])} search(es)"
        )


class FulltextSince(KeysSinceHandler):
    """
    Get the keys of items' fulltext that have been added or modified after 'since'.

    This handler doesn't change anything in the database.
    """

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/fulltext?since={self.delta.since}"
        )


class BatchHandler(SinceHandler, ABC):
    """Base class for handlers that fetch and update a batch of objects identified by their keys."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        batch_num: int,
        batch_size: int,
        batch_keys: list[str],
        done: list[str],
    ):
        self.batch_num = batch_num
        self.batch_size = batch_size
        self.batch_keys = batch_keys
        self.done = done
        super().__init__(zotero_config, delta, db, http)

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}#{self.batch_num} "
            f"[size={self.batch_size} keys={len(self.batch_keys)}]"
        )


class CollectionsBatch(BatchHandler):
    """Fetch and update a batch of collections identified by their keys."""

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/collections?collectionKey={','.join(self.batch_keys)}"
            f"&since={self.delta.since}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.update_collections(response.json())
        self.done.extend(self.batch_keys)


class SearchesBatch(BatchHandler):
    """Fetch and update a batch of searches identified by their keys."""

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/searches?searchKey={','.join(self.batch_keys)}"
            f"&since={self.delta.since}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.update_searches(response.json())
        self.done.extend(self.batch_keys)


class ItemsBatch(BatchHandler):
    """Fetch and update a batch of items identified by their keys."""

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items?itemKey={','.join(self.batch_keys)}"
            f"&since={self.delta.since}&format=json&includeTrashed=1"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.update_items(response.json())
        self.done.extend(self.batch_keys)


class ItemsBibBatch(BatchHandler):
    """Fetch and update a batch of formatted item references identified by item keys."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        batch_num: int,
        batch_size: int,
        batch_keys: list[str],
        done: list[str],
        style: str,
        locale: str,
    ):
        self.style = style
        self.locale = locale
        super().__init__(zotero_config, delta, db, http, batch_num, batch_size, batch_keys, done)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items?itemKey={','.join(self.batch_keys)}"
            f"&since={self.delta.since}&format=json"
            f"&include=bib&style={self.style}&locale={self.locale}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_items_bib(response.json(), style=self.style, locale=self.locale)
        self.done.extend(self.batch_keys)

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}#{self.batch_num} "
            f"[size={self.batch_size} keys={len(self.batch_keys)}] "
            f"style={self.style} locale={self.locale}"
        )


class ItemsExportFormatBatch(BatchHandler):
    """Fetch and update a batch of exported items identified by item keys."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        batch_num: int,
        batch_size: int,
        batch_keys: list[str],
        done: list[str],
        export_format: str,
    ):
        self.export_format = export_format
        super().__init__(zotero_config, delta, db, http, batch_num, batch_size, batch_keys, done)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items?itemKey={','.join(self.batch_keys)}"
            f"&since={self.delta.since}&format=json&include={self.export_format}"
        )

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_items_export_format(response.json(), export_format=self.export_format)
        self.done.extend(self.batch_keys)

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}#{self.batch_num} "
            f"[size={self.batch_size} keys={len(self.batch_keys)}] "
            f"format={self.export_format}"
        )


class ItemFulltext(SinceHandler):
    """Fetch and update the fulltext of an item that has changed since 'since'."""

    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        item_key: str,
    ):
        self.item_key = item_key
        super().__init__(zotero_config, delta, db, http)

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items/{self.item_key}/fulltext"
        )

    async def validate_response(self, response: httpx.Response) -> None:
        pass  # Fulltext doesn't return a version, thus can't check for version change.

    async def process_response(self, response: httpx.Response) -> None:
        self.db.insert_item_fulltext(self.item_key, data=response.json())

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_key={self.item_key}"


class ItemFileDownload(Handler):
    def __init__(
        self,
        zotero_config: Config,
        delta: Delta,
        db: Library,
        http: httpx.AsyncClient,
        dest_dir: Path,
        item_file: dict[str, Any],
    ):
        self.dest_dir = dest_dir
        self.item_file = item_file
        self.file_path = dest_dir / str(item_file["item_key"])
        super().__init__(zotero_config, delta, db, http)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} item_key={self.item_file['item_key']}"

    @property
    def url(self) -> str:
        return (
            f"{self.zotero_config.base_url}/{self.zotero_config.library_prefix}/"
            f"{self.zotero_config.library_id}/items/{self.item_file['item_key']}/file"
        )

    async def request(self) -> httpx.Response:
        # Check if file already exists and has the correct MD5.
        if await self.file_path.exists():
            content = await self.file_path.read_bytes()
            current_md5 = hashlib.md5(content).hexdigest()
            if current_md5 == self.item_file["md5"]:
                self.db.update_item_file_download_status(
                    self.item_file["item_key"],
                    self.db.FILE_DOWNLOAD_STATUS_OK,
                )
                raise SkippedFileAlreadyInSyncError(self.item_file["item_key"])
            logger.debug("Downloading updated attachment %s", self.item_file["item_key"])
        else:
            logger.debug("Downloading new attachment %s", self.item_file["item_key"])

        # Request file from Zotero API.
        return await self.http.get(self.url, headers=self.headers, follow_redirects=True)

    async def process_response(self, response: httpx.Response) -> None:
        # Some things of note:
        # - Zotero file URLs get redirected to a file hosting service.
        # - The content type of the original file will differ from the Content-Type response header
        #   if the served file is compressed.
        # - Zotero adds its own headers to the initial response (before the redirect) to indicate
        #   whether it compressed the file (hence the peek at response history below).
        # - We won't decompress Zotero snapshots (which have the "text/html" content type) as the
        #   zip may contain multiple files.
        # - References:
        #     - https://www.zotero.org/support/dev/web_api/v3/file_upload#i_retrieve_the_attachment_information
        #     - https://groups.google.com/g/zotero-dev/c/ZS7o5ymitFw/m/jo0lzFaUAQAJ

        if (
            response.headers.get("Content-Type") == "application/zip"
            and response.history[0].headers.get("Zotero-File-Compressed") == "Yes"
        ):
            # We're being served a compressed file. The ETag header provides the MD5 of the
            # compressed file, to use instead of the MD5 of the original file.
            expected_md5 = response.headers.get("ETag", "").strip('"')
            # Decompress if this is not a Zotero snapshot.
            decompress = self.item_file["content_type"] != "text/html"
        else:
            # Use the MD5 of the original file.
            expected_md5 = self.item_file["md5"]
            decompress = False

        if expected_md5:
            # Check MD5 against response content.
            downloaded_md5 = hashlib.md5(response.content).hexdigest()
            if downloaded_md5 != expected_md5:
                self.db.update_item_file_download_status(
                    self.item_file["item_key"],
                    self.db.FILE_DOWNLOAD_STATUS_ERROR,
                )
                raise SkippedFileIntegrityError(self.item_file["item_key"])

        content = self._unzip(response.content) if decompress else response.content

        try:
            # Write response to file.
            await self.file_path.write_bytes(content)
            # Set the file modification time.
            mtime_seconds = self.item_file["mtime"] / 1000
            os.utime(self.file_path, (mtime_seconds, mtime_seconds))

        except OSError as exc:
            self.db.update_item_file_download_status(
                self.item_file["item_key"],
                self.db.FILE_DOWNLOAD_STATUS_ERROR,
            )
            raise SkippedFileWriteError(self.item_file["item_key"]) from exc

        else:
            self.db.update_item_file_download_status(
                self.item_file["item_key"],
                self.db.FILE_DOWNLOAD_STATUS_OK,
            )

    def _unzip(self, content: bytes) -> bytes:
        try:
            with zipfile.ZipFile(BytesIO(content)) as zip_file:
                if file_names := zip_file.namelist():
                    return zip_file.read(file_names[0])

            msg = "ZIP contains no files"
            raise ValueError(msg)  # noqa: TRY301
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            raise SkippedFileDecompressionError(self.item_file["item_key"]) from exc
