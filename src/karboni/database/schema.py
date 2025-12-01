"""Database models for mirroring a Zotero library."""

import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Collection(Base):
    __tablename__ = "collection"

    collection_key: Mapped[str] = mapped_column(String(8), primary_key=True)
    version: Mapped[int] = mapped_column(index=True)
    name: Mapped[str]
    parent_collection: Mapped[str | None] = mapped_column(String(8), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)
    links: Mapped[dict[str, Any]] = mapped_column(JSON)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    trashed: Mapped[bool | None] = mapped_column(index=True)  # Zotero API JSON uses "deleted".

    # Relationships.
    items: Mapped[list["Item"]] = relationship(
        "Item",
        secondary="item_collection",
        back_populates="collections",
    )

    def __repr__(self) -> str:
        return (
            f"Collection(collection_key={self.collection_key!r}, "
            f"version={self.version!r}, parent_collection={self.parent_collection!r}, "
            f"trashed={self.trashed!r})"
        )


class ItemType(Base):
    __tablename__ = "item_type"

    item_type: Mapped[str] = mapped_column(primary_key=True)

    def __repr__(self) -> str:
        return f"ItemType(item_type={self.item_type!r})"


class ItemTypeLocale(Base):
    __tablename__ = "item_type_locale"

    item_type: Mapped[str] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(primary_key=True)
    localized: Mapped[str]

    def __repr__(self) -> str:
        return (
            f"ItemTypeLocale(item_type={self.item_type!r}, "
            f"locale={self.locale!r}, localized={self.localized!r})"
        )


class ItemTypeField(Base):
    __tablename__ = "item_type_field"

    item_type: Mapped[str] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(index=True)

    def __repr__(self) -> str:
        return (
            f"ItemTypeField(item_type={self.item_type!r}, "
            f"field={self.field!r}, position={self.position!r})"
        )


class ItemTypeFieldLocale(Base):
    __tablename__ = "item_type_field_locale"

    item_type: Mapped[str] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(primary_key=True)
    localized: Mapped[str]

    def __repr__(self) -> str:
        return (
            f"ItemTypeFieldLocale(item_type={self.item_type!r}, "
            f"field={self.field!r}, locale={self.locale!r}, "
            f"localized={self.localized!r})"
        )


class ItemTypeCreatorType(Base):
    __tablename__ = "item_type_creator_type"

    item_type: Mapped[str] = mapped_column(primary_key=True)
    creator_type: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(index=True)

    def __repr__(self) -> str:
        return (
            f"ItemTypeCreatorType(item_type={self.item_type!r}, "
            f"creator_type={self.creator_type!r}, position={self.position!r})"
        )


class ItemTypeCreatorTypeLocale(Base):
    __tablename__ = "item_type_creator_type_locale"

    item_type: Mapped[str] = mapped_column(primary_key=True)
    creator_type: Mapped[str] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(primary_key=True)
    localized: Mapped[str]

    def __repr__(self) -> str:
        return (
            f"ItemTypeCreatorTypeLocale(item_type={self.item_type!r}, "
            f"creator_type={self.creator_type!r}, locale={self.locale!r}, "
            f"localized={self.localized!r})"
        )


class Item(Base):
    __tablename__ = "item"

    item_key: Mapped[str] = mapped_column(String(8), primary_key=True)
    version: Mapped[int] = mapped_column(index=True)
    item_type: Mapped[str] = mapped_column(index=True)
    parent_item: Mapped[str | None] = mapped_column(String(8), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)
    links: Mapped[dict[str, Any]] = mapped_column(JSON)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    relations: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trashed: Mapped[bool | None] = mapped_column(index=True)  # Zotero API JSON uses "deleted".

    # Relationships.
    collections: Mapped[list["Collection"]] = relationship(
        "Collection",
        secondary="item_collection",
        back_populates="items",
    )
    tags: Mapped[list["ItemTag"]] = relationship(
        "ItemTag",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    bib: Mapped[list["ItemBib"]] = relationship(
        "ItemBib",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    export_formats: Mapped[list["ItemExportFormat"]] = relationship(
        "ItemExportFormat",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    file: Mapped["ItemFile | None"] = relationship(
        "ItemFile",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    fulltext: Mapped["ItemFulltext | None"] = relationship(
        "ItemFulltext",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"Item(item_key={self.item_key!r}, version={self.version!r}, "
            f"item_type={self.item_type!r}, parent_item={self.parent_item!r}, "
            f"trashed={self.trashed!r})"
        )


class ItemCollection(Base):
    __tablename__ = "item_collection"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_key: Mapped[str] = mapped_column(
        ForeignKey("collection.collection_key", ondelete="CASCADE"),
        primary_key=True,
    )

    def __repr__(self) -> str:
        return f"ItemCollection(item_key={self.item_key!r}, collection_key={self.collection_key!r})"


class ItemTag(Base):
    __tablename__ = "item_tag"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(primary_key=True)

    # Relationships.
    item: Mapped["Item"] = relationship("Item", back_populates="tags")

    def __repr__(self) -> str:
        return f"ItemTag(item_key={self.item_key!r}, tag={self.tag!r})"


class ItemBib(Base):
    __tablename__ = "item_bib"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    style: Mapped[str] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(primary_key=True)
    bib: Mapped[str]

    # Relationships.
    item: Mapped["Item"] = relationship("Item", back_populates="bib")

    def __repr__(self) -> str:
        return f"ItemBib(item_key={self.item_key!r}, style={self.style!r}, locale={self.locale!r})"


class ItemExportFormat(Base):
    __tablename__ = "item_export_format"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    format: Mapped[str] = mapped_column(primary_key=True)
    content: Mapped[str]

    # Relationships.
    item: Mapped["Item"] = relationship("Item", back_populates="export_formats")

    def __repr__(self) -> str:
        return f"ItemExportFormat(item_key={self.item_key!r}, format={self.format!r})"


class ItemFile(Base):
    __tablename__ = "item_file"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    content_type: Mapped[str] = mapped_column(index=True)
    charset: Mapped[str]
    filename: Mapped[str]
    md5: Mapped[str | None] = mapped_column(String(32))
    mtime: Mapped[int | None] = mapped_column(BigInteger)
    download_status: Mapped[str] = mapped_column(index=True)

    # Relationships.
    item: Mapped["Item"] = relationship("Item", back_populates="file")

    def __repr__(self) -> str:
        return (
            f"ItemFile(item_key={self.item_key!r}, "
            f"filename={self.filename!r}, content_type={self.content_type!r}, "
            f"download_status={self.download_status!r})"
        )


class ItemFulltext(Base):
    __tablename__ = "item_fulltext"

    item_key: Mapped[str] = mapped_column(
        ForeignKey("item.item_key", ondelete="CASCADE"),
        primary_key=True,
    )
    content: Mapped[str]
    indexed_pages: Mapped[int | None]
    total_pages: Mapped[int | None]
    indexed_chars: Mapped[int | None]
    total_chars: Mapped[int | None]

    # Relationships.
    item: Mapped["Item"] = relationship("Item", back_populates="fulltext")

    def __repr__(self) -> str:
        return f"ItemFulltext(item_key={self.item_key!r})"


class Search(Base):
    __tablename__ = "search"

    search_key: Mapped[str] = mapped_column(String(8), primary_key=True)
    version: Mapped[int] = mapped_column(index=True)
    name: Mapped[str]
    links: Mapped[dict[str, Any]] = mapped_column(JSON)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    trashed: Mapped[bool | None] = mapped_column(index=True)  # Zotero API JSON uses "deleted".

    def __repr__(self) -> str:
        return (
            f"Search(search_key={self.search_key!r}, version={self.version!r}, name={self.name!r}, "
            f"trashed={self.trashed!r})"
        )


class DeletedCollection(Base):
    __tablename__ = "deleted_collection"

    collection_key: Mapped[str] = mapped_column(String(8), primary_key=True)

    def __repr__(self) -> str:
        return f"DeletedCollection(collection_key={self.collection_key!r})"


class DeletedItem(Base):
    __tablename__ = "deleted_item"

    item_key: Mapped[str] = mapped_column(String(8), primary_key=True)

    def __repr__(self) -> str:
        return f"DeletedItem(item_key={self.item_key!r})"


class DeletedSearch(Base):
    __tablename__ = "deleted_search"

    search_key: Mapped[str] = mapped_column(String(8), primary_key=True)

    def __repr__(self) -> str:
        return f"DeletedSearch(search_key={self.search_key!r})"


class SyncHistory(Base):
    __tablename__ = "sync_history"

    history_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[str]
    library_prefix: Mapped[str]
    since_version: Mapped[int] = mapped_column(index=True)
    to_version: Mapped[int] = mapped_column(index=True)
    started_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    ended_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    data_options: Mapped[dict[str, Any]] = mapped_column(JSON)
    process_options: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_item_count: Mapped[int]
    updated_item_fulltext_count: Mapped[int]
    updated_collection_count: Mapped[int]
    updated_search_count: Mapped[int]
    deleted_item_count: Mapped[int]
    deleted_collection_count: Mapped[int]
    deleted_search_count: Mapped[int]
    files_started_on: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    files_ended_on: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    updated_file_count: Mapped[int | None]
    deleted_file_count: Mapped[int | None]
    karboni_version: Mapped[str]
