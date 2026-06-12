# Changelog

## 0.1.0 (2026-06-12)

Bug fixes:

- Fix sync crashing when an item's fulltext has changed but not the item itself.
- Fix sync crashing with export format `csljson`.

Other changes:

- Fix minor code style and type annotation issues.


## 0.1.0alpha2 (2026-02-27)

Bug fixes:

- Fix `.env` file not looked up in arbitrary working directory.

Other changes:

- Replace variables `Library.FILE_DOWNLOAD_STATUS_*` with enum `Library.FileDownloadStatus`.
- Simplify file attachments cleaning code.


## 0.1.0alpha1 (2025-12-16)

Bug fixes:

- Fix subcollections not deleted when a collection gets deleted.
- Fix item type information lost in some incremental sync scenarios.
- Fix database engine connection not cleanly disposed of after use.
- Fix sync parameter consistency check sometimes failing.
- Fix crash when passing duplicate values to locales, styles, export_formats or
  media_types options.

Other changes:

- Rename `max_requests` option to `max_concurrent_requests`.
- Remove unused optional package dependencies.
- Standardize the interfaces of exception classes.
- Add documentation.


## 0.1.0alpha0 (2025-12-01)

- First PyPI release.
