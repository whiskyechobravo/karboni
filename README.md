# Karboni

Mirror a Zotero library into a SQL database.


## Features

- Fast one-way synchronization from Zotero to a SQL database.
- Fetch library items, collections, tags, saved searches metadata.
- Download file attachments.
- Fetch formatted references in multiple bibliographic styles, for multiple
  locales.
- Fetch multiple export formats.
- Fetch the full text content of items.
- Fetch the labels of item types, field names and creator types, for multiple
  locales.
- Python API for managing synchronization.
- Command line interface for managing synchronization.
- Support for a wide range of database systems (through SQLAlchemy).


## Python interface

The `karboni` Python module provides the main entry points, with functions such
as `initialize()` and `synchronize()`.

If you wish to use SQLAlchemy for querying the database, you might want to
import models from `karboni.database.schema`.


## Command line interface

To use the command line interface, you must first configure your Zotero
credentials in environment variables, or in a `.env` file. You could copy the
included `template.env` to `.env` and edit the values.

The required variables are:

- `ZOTERO_LIBRARY_PREFIX`
- `ZOTERO_LIBRARY_ID`
- `ZOTERO_API_KEY`

Optional variables are:

- `KARBONI_DATABASE_URL` (defaults to `sqlite:///data/karboni/${ZOTERO_LIBRARY_PREFIX}-${ZOTERO_LIBRARY_ID}/library.sqlite`)
- `KARBONI_DATA_PATH` (defaults to `./data/karboni/${ZOTERO_LIBRARY_PREFIX}-${ZOTERO_LIBRARY_ID}/`)

Once the required variables have been set, you may operate Karboni. Some
examples below.

Initialize the mirror database (create the tables):

```sh
karboni init
```

Synchronize from Zotero:

```sh
karboni sync
```

List the available commands and general options:

```sh
karboni --help
```

List the options of a given command:

```sh
karboni COMMAND --help
```


## Design choices

Here are some of the design choices that have guided the development of Karboni:

- Perform Zotero API requests and file IO asynchronously to minimize idle time.
- Use SQLite as the baseline database system, reducing the need for additional
  dependencies (it's included in the Python standard library), but interface it
  through SQLAlchemy in order to support other databases as well.
- Since Karboni itself only needs a few simple database operations, encapsulate
  SQLAlchemy under a thin abstraction layer to decouple the synchronization
  process from the database toolkit.
- Stay close to the Zotero schema. Store data in the JSON format provided by the
  Zotero API whenever possible, for consistency and better adaptability to
  future Zotero schema changes. Add SQL columns where they can be useful to the
  synchronization process or to allow basic queries.
- Don't fuss too much with database-level referential integrity constraints.
  Leave that to Zotero. In particular, the keys of parent items and parent
  collections are not validated (this simplifies the synchronization process).
- Don't worry about database schema migrations. The database is just a mirror,
  thus its tables can be wiped when necessary and re-synchronized from Zotero.
- Synchronization of file attachments is not atomic. If library synchronization
  finishes but file downloads fail, we accept that and don't rollback the
  database changes.


## Known limitations

- Database operations are synchronous because SQLAlchemy cannot (at least not
  easily) share a session between concurrent tasks.
- During transactions, SQLite locks database access from other threads or
  processes. When synchronizing from Zotero, Karboni applies all changes in a
  single transaction (to allow rollback in case of failure), which means the
  database can remain locked for some time. To ensure availability during
  synchronization, use a database system that has more advanced locking
  mechanisms (such as PostgreSQL or MySQL).
- Python 3.11+ is required (it facilitates exception handling with asynchronous
  tasks).
