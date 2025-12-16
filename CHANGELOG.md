# Changelog

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
