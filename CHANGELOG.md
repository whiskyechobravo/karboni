# Changelog

## Unreleased

Bug fixes:

- Fix item type information lost in incremental synchronization scenarios where
  the only changes involved collections, full texts, searches, or deletions.
- Fix database engine connection not cleanly disposed of after use.
- Fix sync parameter consistency check sometimes failing.
- Fix crash when passing duplicate values to locales, styles, export_formats or
  media_types options.

Other changes:

- Rename max_requests option to max_concurrent_requests.
- Remove unused optional package dependencies.
- Add documentation.


## 0.1.0alpha0 (2025-12-01)

- First PyPI release.
