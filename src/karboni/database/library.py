import datetime
import json
import logging
from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from types import TracebackType
from typing import Any, TypeVar

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from karboni import __version__
from karboni.database.engine import create_engine
from karboni.database.schema import (
    Collection,
    DeletedCollection,
    DeletedItem,
    DeletedSearch,
    Item,
    ItemBib,
    ItemCollection,
    ItemExportFormat,
    ItemFile,
    ItemFulltext,
    ItemTag,
    ItemType,
    ItemTypeCreatorType,
    ItemTypeCreatorTypeLocale,
    ItemTypeField,
    ItemTypeFieldLocale,
    ItemTypeLocale,
    Search,
    SyncHistory,
)
from karboni.exceptions import DatabaseNotInitializedError
from karboni.typing import VersionType

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def write_operation(func: F) -> F:
    """Raises RuntimeError if F is called while database in read-only mode."""

    @wraps(func)
    def wrapper(self: "Library", *args: Any, **kwargs: Any) -> Any:
        if self._readonly:
            msg = "Cannot perform write operation in read-only mode"
            raise RuntimeError(msg)
        return func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class Library:
    """
    Interface with SQLAlchemy to manage a Zotero library mirror.

    This thin interface layer provides the minimal operations required to mirror
    a Zotero library, and protects the caller from dealing with SQLAlchemy
    specifics.
    """

    class FileDownloadStatus(StrEnum):
        UNAVAILABLE = "unavailable"  # File that Zotero is unable to provide.
        UNKNOWN = "unknown"  # File not required and had no fetch attempt.
        OK = "ok"  # File has been successfully fetched.
        ERROR = "error"  # File fetching or saving has failed.
        DELETED = "deleted"  # File is known to have been removed locally.

    def __init__(self, database_url: str, readonly: bool = False) -> None:
        self._readonly = readonly
        self._database_url = database_url

        logger.debug("Open database session")
        self._engine = create_engine(self._database_url)

        self._check_database()

        if self._readonly:
            self._session = Session(self._engine, autoflush=False, autocommit=False)
        else:
            self._session = Session(self._engine)

        if not self._readonly:
            self._session.begin()

    def _check_database(self) -> None:
        """Check if the database has been initialized."""
        # Use SQLAlchemy's introspection to check if any tables exist.
        if not inspect(self._engine).get_table_names():
            raise DatabaseNotInitializedError(self._database_url)

    @property
    def readonly(self) -> bool:
        return self._readonly

    def __enter__(self) -> "Library":
        """Enter the session context. This allows usage in a with block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Exit the session context.

        Commits the transaction if no exception occurred, otherwise rolls back
        the transaction. Always closes the session.
        """
        if not self._readonly:
            if exc_val:
                self.rollback()
            else:
                self.commit()
        self.close()

    def close(self) -> None:
        """Close the session, committing any pending transactions and releasing any resources."""
        logger.debug("Close database session")
        self._session.close()
        self._engine.dispose()

    @write_operation
    def commit(self) -> None:
        """Commit the current transaction, persisting all changes to the database."""
        logger.debug("Commit transaction")
        self._session.commit()

    @write_operation
    def rollback(self) -> None:
        """Roll back the current transaction, discarding any uncommitted changes."""
        logger.debug("Rollback transaction")
        self._session.rollback()

    def version(self) -> VersionType | None:
        """Return the mirror database's version. Returns None if the database has no version yet."""
        stmt = select(SyncHistory.to_version).order_by(SyncHistory.history_id.desc()).limit(1)
        return self._session.scalar(stmt)

    @write_operation
    def delete_all(self) -> None:
        """Delete all data from the mirror database."""
        logger.debug("Deleting all data from mirror database")
        self.delete_all_item_types()
        self.delete_all_collections()
        self.delete_all_searches()
        self.delete_all_items()
        self.delete_all_deleted_objects()
        self.delete_all_sync_history()

    @write_operation
    def delete_all_item_types(self) -> None:
        """Delete all item types, cascading to related tables."""
        for table in (
            ItemType,
            ItemTypeLocale,
            ItemTypeField,
            ItemTypeFieldLocale,
            ItemTypeCreatorType,
            ItemTypeCreatorTypeLocale,
        ):
            self._delete_all_table_rows(table)

    @write_operation
    def delete_all_collections(self) -> None:
        """Delete all collections, cascading to related tables."""
        for table in (ItemCollection, Collection):
            self._delete_all_table_rows(table)

    @write_operation
    def delete_all_items(self) -> None:
        """Delete all items, cascading to related tables."""
        for table in (
            ItemCollection,
            ItemTag,
            ItemBib,
            ItemExportFormat,
            ItemFile,
            ItemFulltext,
            Item,
        ):
            self._delete_all_table_rows(table)

    @write_operation
    def delete_all_searches(self) -> None:
        self._delete_all_table_rows(Search)

    @write_operation
    def delete_all_deleted_objects(self) -> None:
        """Delete all records of deleted collections, items, searches."""
        for table in (DeletedCollection, DeletedItem, DeletedSearch):
            self._delete_all_table_rows(table)

    @write_operation
    def _bulk_delete_objects(self, table: Any, column: str, values: list[Any]) -> None:
        stmt = delete(table).where(getattr(table, column).in_(values))
        self._session.execute(stmt)

    @write_operation
    def _delete_all_table_rows(self, table: Any) -> None:
        stmt = delete(table)
        self._session.execute(stmt)

    @write_operation
    def merge_item_types(self, item_types: list[Any]) -> None:
        """
        Insert or update the specified item types.

        Performs consecutive bulk deletions and insertions for better performance.
        """
        logger.debug("Update %d item type(s)", len(item_types))
        self.bulk_delete_item_types(item_types)
        self.bulk_insert_item_types(item_types)

    @write_operation
    def bulk_delete_item_types(self, item_types: list[Any]) -> None:
        for table in (
            ItemType,
            ItemTypeLocale,
            ItemTypeField,
            ItemTypeFieldLocale,
            ItemTypeCreatorType,
            ItemTypeCreatorTypeLocale,
        ):
            self._bulk_delete_objects(table, "item_type", [t["itemType"] for t in item_types])

    @write_operation
    def bulk_insert_item_types(self, item_types: list[Any]) -> None:
        item_type_objects = [{"item_type": t["itemType"]} for t in item_types]
        self._session.bulk_insert_mappings(ItemType, item_type_objects)  # type: ignore[arg-type]

    @write_operation
    def insert_item_types_locale(self, item_types: list[Any], locale: str) -> None:
        obj = [
            {"item_type": t["itemType"], "locale": locale, "localized": t["localized"]}
            for t in item_types
        ]
        if obj:
            self._session.bulk_insert_mappings(ItemTypeLocale, obj)  # type: ignore[arg-type]

    @write_operation
    def insert_item_type_fields(self, fields: list[Any], item_type: str) -> None:
        obj = [
            {"item_type": item_type, "field": f["field"], "position": i}
            for i, f in enumerate(fields)
        ]
        if obj:
            self._session.bulk_insert_mappings(ItemTypeField, obj)  # type: ignore[arg-type]

    @write_operation
    def insert_item_type_fields_locale(
        self, fields: list[Any], item_type: str, locale: str
    ) -> None:
        obj = [
            {
                "item_type": item_type,
                "field": f["field"],
                "locale": locale,
                "localized": f["localized"],
            }
            for f in fields
        ]
        if obj:
            self._session.bulk_insert_mappings(ItemTypeFieldLocale, obj)  # type: ignore[arg-type]

    @write_operation
    def insert_item_type_creator_types(self, creator_types: list[Any], item_type: str) -> None:
        obj = [
            {"item_type": item_type, "creator_type": f["creatorType"], "position": i}
            for i, f in enumerate(creator_types)
        ]
        if obj:
            self._session.bulk_insert_mappings(ItemTypeCreatorType, obj)  # type: ignore[arg-type]

    @write_operation
    def insert_item_type_creator_types_locale(
        self, creator_types: list[Any], item_type: str, locale: str
    ) -> None:
        obj = [
            {
                "item_type": item_type,
                "creator_type": f["creatorType"],
                "locale": locale,
                "localized": f["localized"],
            }
            for f in creator_types
        ]
        if obj:
            self._session.bulk_insert_mappings(ItemTypeCreatorTypeLocale, obj)  # type: ignore[arg-type]

    @write_operation
    def merge_collections(self, collections: list[Any]) -> None:
        """
        Insert or update the specified collections.

        Uses slower individual merge updates instead of consecutive bulk delete and bulk insert
        operations, to avoid cascade deletion of ItemCollection relationships.
        """
        keys = [collection["key"] for collection in collections]
        logger.debug("Update %d collections: %s", len(collections), repr(keys))

        for collection in collections:
            collection_object = Collection(
                collection_key=collection["key"],
                version=collection["version"],
                name=collection["data"].get("name", ""),
                parent_collection=collection["data"].get("parentCollection") or None,
                meta=collection["meta"],
                links=collection["links"],
                data=collection["data"],
                trashed=collection["data"].get("deleted"),
            )
            self._session.merge(collection_object)

    def find_subcollection(self, collection_key: str) -> list[str]:
        descendants = []
        queue = [collection_key]
        while queue:
            current = queue.pop(0)
            stmt = select(Collection.collection_key).where(Collection.parent_collection == current)
            children = list(self._session.scalars(stmt).all())
            descendants.extend(children)
            queue.extend(children)
        return descendants

    @write_operation
    def bulk_delete_collections(self, keys: list[str]) -> None:
        self._bulk_delete_objects(Collection, "collection_key", keys)

    @write_operation
    def bulk_insert_collections(self, collections: list[Any]) -> None:
        # Prepare data for bulk insertion.
        collection_objects = [
            {
                "collection_key": collection["key"],
                "version": collection["version"],
                "name": collection["data"].get("name", ""),
                "parent_collection": collection["data"].get("parentCollection") or None,
                "meta": collection["meta"],
                "links": collection["links"],
                "data": collection["data"],
                "trashed": collection["data"].get("deleted"),
            }
            for collection in collections
        ]

        # Bulk insert data.
        if collection_objects:
            self._session.bulk_insert_mappings(Collection, collection_objects)  # type: ignore[arg-type]

    @write_operation
    def merge_searches(self, searches: list[Any]) -> None:
        """
        Insert or update the specified searches.

        Performs consecutive bulk deletions and insertions for better performance.
        """
        # Use fast bulk operations instead of individual merges.
        keys = [search["key"] for search in searches]
        logger.debug("Update %d searches: %s", len(searches), repr(keys))
        self.bulk_delete_searches(keys)
        self.bulk_insert_searches(searches)

    @write_operation
    def bulk_delete_searches(self, keys: list[str]) -> None:
        self._bulk_delete_objects(Search, "search_key", keys)

    @write_operation
    def bulk_insert_searches(self, searches: list[Any]) -> None:
        # Prepare data for bulk insertion.
        search_objects = [
            {
                "search_key": search["key"],
                "version": search["version"],
                "name": search["data"].get("name", ""),
                "links": search["links"],
                "data": search["data"],
                "trashed": search["data"].get("deleted"),
            }
            for search in searches
        ]

        # Bulk insert data.
        if search_objects:
            self._session.bulk_insert_mappings(Search, search_objects)  # type: ignore[arg-type]

    @write_operation
    def merge_items(self, items: list[Any]) -> None:
        """
        Insert or update the specified items.

        Performs consecutive bulk deletions and insertions on related tables for better performance.
        Related data such as ItemBib and ItemExportFormat must be re-inserted through separate
        operations.

        However, slower individual merge updates are used for the Item table, in order to avoid
        cascade deletion of related ItemFulltext entries. The latter cannot be deleted here because
        items and their fulltext have separate lifecycles in the Zotero API.
        """
        keys = [item["key"] for item in items]
        logger.debug("Update %d items: %s", len(items), repr(keys))

        # Bulk delete related tables first.
        self._bulk_delete_items_related(keys)

        # Merge items individually.
        for item in items:
            item_object = Item(
                item_key=item["key"],
                version=item["version"],
                item_type=item["data"].get("itemType", ""),
                parent_item=item["data"].get("parentItem"),
                meta=item["meta"],
                links=item["links"],
                data=item["data"],
                relations=item["data"].get("relations"),
                trashed=item["data"].get("deleted"),
            )
            self._session.merge(item_object)

        # Flush merged items before inserting related data, to satisfy foreign key constraints.
        self._session.flush()

        # Bulk insert related data.
        self._bulk_insert_items_related(items)

    @write_operation
    def bulk_delete_items(self, keys: list[str]) -> None:
        """Delete items, cascading to all related tables, including ItemFulltext."""
        # Handle the cascades because ORM bulk deletion does not trigger
        # database-level cascades.
        for model in (
            ItemCollection,
            ItemTag,
            ItemBib,
            ItemExportFormat,
            ItemFile,
            ItemFulltext,
            Item,
        ):
            self._bulk_delete_objects(model, "item_key", keys)

    @write_operation
    def _bulk_delete_items_related(self, keys: list[str]) -> None:
        """Delete entries from tables related to Item, excluding ItemFulltext."""
        for model in (
            ItemCollection,
            ItemTag,
            ItemBib,
            ItemExportFormat,
            ItemFile,
        ):
            self._bulk_delete_objects(model, "item_key", keys)

    @write_operation
    def _bulk_insert_items_related(self, items: list[Any]) -> None:
        # Prepare data for bulk insertion.
        collection_objects = []
        tag_objects = []
        file_objects = []
        for item in items:
            collection_objects.extend(
                [
                    {"item_key": item["key"], "collection_key": collection_key}
                    for collection_key in item["data"].get("collections", [])
                ]
            )
            tag_objects.extend(
                [
                    {"item_key": item["key"], "tag": tag["tag"]}
                    for tag in item["data"].get("tags", [])
                ]
            )

            # If item has a filename and is not a linked file, it must be downloadable.
            if (
                item["data"].get("itemType") == "attachment"
                and item["data"].get("filename")
                and item["data"].get("linkMode") != "linked_file"
            ):
                if item["data"].get("md5") is None:
                    download_status = self.FileDownloadStatus.UNAVAILABLE
                else:
                    download_status = self.FileDownloadStatus.UNKNOWN

                file_objects.append(
                    {
                        "item_key": item["key"],
                        "content_type": item["data"].get("contentType", ""),
                        "charset": item["data"].get("charset", ""),
                        "filename": item["data"].get("filename", ""),
                        "md5": item["data"].get("md5"),  # Can be None if file is unavailable.
                        "mtime": item["data"].get("mtime"),  # Can be None if file is unavailable.
                        "download_status": download_status,
                    }
                )

        # Bulk insert data.
        if collection_objects:
            self._session.bulk_insert_mappings(ItemCollection, collection_objects)  # type: ignore[arg-type]
        if tag_objects:
            self._session.bulk_insert_mappings(ItemTag, tag_objects)  # type: ignore[arg-type]
        if file_objects:
            self._session.bulk_insert_mappings(ItemFile, file_objects)  # type: ignore[arg-type]

    @write_operation
    def insert_items_bib(self, items: list[Any], style: str, locale: str) -> None:
        """Insert the specified item formatted references."""
        obj = [
            {"item_key": item["key"], "style": style, "locale": locale, "bib": item["bib"]}
            for item in items
        ]

        if obj:
            self._session.bulk_insert_mappings(ItemBib, obj)  # type: ignore[arg-type]

    @write_operation
    def insert_items_export_format(self, items: list[Any], export_format: str) -> None:
        """Insert the specified item export formats."""
        obj = [
            {
                "item_key": item["key"],
                "format": export_format,
                "content": item[export_format]
                if isinstance(item[export_format], str)
                else json.dumps(item[export_format]),
            }
            for item in items
        ]

        if obj:
            self._session.bulk_insert_mappings(ItemExportFormat, obj)  # type: ignore[arg-type]

    @write_operation
    def bulk_delete_items_fulltext(self, keys: list[str]) -> None:
        self._bulk_delete_objects(ItemFulltext, "item_key", keys)

    @write_operation
    def insert_item_fulltext(self, item_key: str, data: dict[str, Any]) -> None:
        """Insert the specified items' fulltext."""
        obj = {
            "item_key": item_key,
            "content": data["content"],
            "indexed_pages": data.get("indexedPages"),
            "total_pages": data.get("totalPages"),
            "indexed_chars": data.get("indexedChars"),
            "total_chars": data.get("totalChars"),
        }
        self._session.bulk_insert_mappings(ItemFulltext, [obj])  # type: ignore[arg-type]

    @write_operation
    def insert_deleted_collections(self, keys: list[str]) -> None:
        # Prepare data for bulk insertion.
        objects = [{"collection_key": key} for key in keys]

        # Bulk insert data.
        if objects:
            self._session.bulk_insert_mappings(DeletedCollection, objects)  # type: ignore[arg-type]

    @write_operation
    def insert_deleted_items(self, keys: list[str]) -> None:
        # Prepare data for bulk insertion.
        objects = [{"item_key": key} for key in keys]

        # Bulk insert data.
        if objects:
            self._session.bulk_insert_mappings(DeletedItem, objects)  # type: ignore[arg-type]

    @write_operation
    def insert_deleted_searches(self, keys: list[str]) -> None:
        # Prepare data for bulk insertion.
        objects = [{"search_key": key} for key in keys]

        # Bulk insert data.
        if objects:
            self._session.bulk_insert_mappings(DeletedSearch, objects)  # type: ignore[arg-type]

    @write_operation
    def insert_sync_history(
        self,
        **kwargs: Any,
    ) -> int:
        """Insert a sync history record and return its ID."""
        sync_history = SyncHistory(**kwargs, karboni_version=__version__)
        self._session.add(sync_history)
        self._session.flush()  # Flush to get the auto-generated ID
        return sync_history.history_id

    @write_operation
    def update_sync_history(self, history_id: int, **kwargs: Any) -> None:
        """Update an existing sync history record."""
        stmt = update(SyncHistory).where(SyncHistory.history_id == history_id).values(**kwargs)
        self._session.execute(stmt)

    @write_operation
    def delete_all_sync_history(self) -> None:
        self._delete_all_table_rows(SyncHistory)

    def last_sync(self) -> dict[str, Any] | None:
        """Return the last sync history record as a dict, or None if there is none."""
        stmt = select(SyncHistory).order_by(SyncHistory.history_id.desc()).limit(1)
        latest = self._session.scalar(stmt)
        if latest is None:
            return None

        # Convert model instance to dict.
        result = {}
        for c in inspect(latest).mapper.column_attrs:
            value = getattr(latest, c.key)
            if isinstance(value, datetime.datetime) and value.tzinfo is None:
                # Although our schema defines DateTime columns with timezone enabled, many database
                # engines don't save that timezone information. Since all our datetimes use UTC
                # anyway, let's fix those naive datetimes.
                value = value.replace(tzinfo=datetime.UTC)
            result[c.key] = value
        return result

    def files_to_download(self, content_types: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Return some details of the item files that need to be fetched.

        Items that are marked as trashed are not included.
        """
        # Note: Depending on its linkMode, an attachment item does not always have a downloadable
        # file. The ItemFile table lists just the downloadable files, hence the query against
        # ItemFile rather than Item.
        stmt = (
            select(ItemFile.item_key, ItemFile.content_type, ItemFile.md5, ItemFile.mtime)
            .join(Item, Item.item_key == ItemFile.item_key)
            .where(
                Item.trashed.is_not(True),
                ItemFile.download_status.in_(
                    [
                        self.FileDownloadStatus.UNKNOWN,
                        self.FileDownloadStatus.ERROR,
                    ]
                ),
            )
        )
        if content_types:
            stmt = stmt.where(ItemFile.content_type.in_(content_types))
        result = self._session.execute(stmt)
        return [dict(row) for row in result.mappings()]

    def files_to_delete(self) -> list[str]:
        """Return the item keys of files that need to be deleted."""
        # TODO: Also mark for deletion item files whose *parent* item is marked as trashed? In the
        # Zotero client, I observe that trashing an item causes its attachment to remain attached
        # (and thus show directly under the trashed item), but does not causes the attachment to get
        # the trashed flag. Not trashing the child might force Karboni users to perform additional
        # checks to distinguish trashed attachments.
        # TODO: Deleting trashed files should probably be optional.
        stmt = (
            select(ItemFile.item_key)
            .join(Item, Item.item_key == ItemFile.item_key)
            .where(
                Item.trashed.is_(True),
                ~ItemFile.download_status.in_(
                    [
                        self.FileDownloadStatus.DELETED,
                        self.FileDownloadStatus.UNAVAILABLE,
                    ]
                ),
            )
        )
        return list(self._session.scalars(stmt).all())

    @write_operation
    def update_item_file_download_status(self, item_key: str, download_status: str) -> None:
        stmt = (
            update(ItemFile)
            .where(ItemFile.item_key == item_key)
            .values(download_status=download_status)
        )
        self._session.execute(stmt)
