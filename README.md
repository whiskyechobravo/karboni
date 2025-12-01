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


## Installation

It is recommended that you install the package in a virtual environment.

The installation steps might look like the following. Replace `DIR` with the
desired path for your new virtual environment.

### Unix/macOS

Create the virtual environment:

```sh
python3 -m venv DIR
```

Activate the virtual environment:

```sh
source DIR/bin/activate
```

Install Karboni:

```sh
python3 -m pip install karboni
```

### Windows

Create the virtual environment:

```
py -m venv DIR
```

Activate the virtual environment:

```
DIR\Scripts\activate
```

Install Karboni:

```
py -m pip install karboni
```


## Command line interface

In order to use the command line interface, you must first configure your Zotero
credentials. With a text editor, create a `.env` file in your working directory
with the following content:

```
ZOTERO_LIBRARY_PREFIX=your_library_prefix
ZOTERO_LIBRARY_ID=your_library_id
ZOTERO_API_KEY=your_api_key
```

Replace `your_library_prefix` with `users` for a personal library, or `groups`
for a group library.

Replace `your_library_id` with the identifier of your library. For a personal
library the value is your user ID, as found on
https://www.zotero.org/settings/keys (you must be logged-in). For a group
library this value is the group ID of the library, as found in the URL of the
library (e.g., the groupID of the library at
`https://www.zotero.org/groups/1234567/example` is `1234567`).

Replace `your_api_key` with your Zotero API key. You may create one for your
library on https://www.zotero.org/settings/keys/new (you must be logged-in).
Karboni does not need to write to your library. Thus, we recommend that your API
key be read-only, and that it does not grant any more access to your Zotero data
than strictly necessary.

By default, Karboni commands will manage data in a `data/karboni` directory
under your current directory, and use SQLite as the relational database. You may
change those defaults by setting the following variables in your `.env` file:

- `KARBONI_DATA_PATH`. Defaults to
  `./data/karboni/ZOTERO_LIBRARY_PREFIX-ZOTERO_LIBRARY_ID/`.
- `KARBONI_DATABASE_URL`. Defaults to
  `sqlite:///data/karboni/ZOTERO_LIBRARY_PREFIX-ZOTERO_LIBRARY_ID/library.sqlite`.
  For other relational databases, see the [SQLAlchemy documentation on database
  URLs](https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls).

Once the required variables have been set, you may use Karboni commands. If you
have installed Karboni in a virtual environment, make sure it is active before
attempting to use the commands (see the activation command in the Installation
section). Some example commands below.

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


## Python interface

The `karboni` Python module provides the main entry points, with functions such
as `initialize()` and `synchronize()`.

If you wish to use SQLAlchemy for querying the database, you might want to
import models from `karboni.database.schema`.


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
