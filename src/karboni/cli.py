import logging
import os
from pathlib import Path
from typing import Any

import click
from click_option_group import optgroup
from dotenv import load_dotenv

from karboni import database
from karboni.logging_utils import setup_logging

logger = logging.getLogger(__name__)


class EnvironmentVariableRequiredError(click.UsageError):
    """Raised when a required environment variable is not set."""

    def __init__(self, variable: str) -> None:
        self.variable = variable

    def __str__(self) -> str:
        return f"Environment variable {self.variable} is required"


class EnvironmentVariableInvalidError(click.UsageError):
    """Raised when an environment variable has an invalid value."""

    def __init__(self, variable: str, value: Any, advice: str) -> None:
        self.variable = variable
        self.value = value
        self.advice = advice

    def __str__(self) -> str:
        return (
            f"Environment variable {self.variable} has invalid value {self.value!r}. {self.advice}"
        )


def get_default_data_path(library_id: str, library_prefix: str) -> Path:
    return Path(f"./data/karboni/{library_prefix}-{library_id}")


def get_database_credentials(library_id: str, library_prefix: str) -> str:
    """Get database credentials from environment variable."""
    database_url = os.getenv("KARBONI_DATABASE_URL")
    if database_url:
        logger.info("Found KARBONI_DATABASE_URL, using %s", database_url)
    else:
        path = get_default_data_path(library_id, library_prefix)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///data/karboni/{library_prefix}-{library_id}/library.sqlite"
        logger.info("Variable KARBONI_DATABASE_URL not set, using default %s", database_url)
    return database_url


def get_data_path(library_id: str, library_prefix: str) -> Path:
    """Get data directory path from environment variable."""
    path_str = os.getenv("KARBONI_DATA_PATH")
    if path_str:
        path = Path(path_str)
        logger.info("Found KARBONI_DATA_PATH, using %s", path)
    else:
        path = get_default_data_path(library_id, library_prefix)
        logger.info("Variable KARBONI_DATA_PATH not set, using default %s", path)

    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    return path.resolve()


def get_zotero_credentials() -> tuple[str, str, str]:
    """Get Zotero credentials from environment variables."""
    variable = "ZOTERO_LIBRARY_ID"
    library_id = os.getenv(variable)
    if not library_id:
        raise EnvironmentVariableRequiredError(variable)
    if not library_id.isdigit():
        raise EnvironmentVariableInvalidError(variable, library_id, "Must be numeric")

    variable = "ZOTERO_LIBRARY_PREFIX"
    library_prefix = os.getenv(variable)
    if not library_prefix:
        raise EnvironmentVariableRequiredError(variable)
    if library_prefix not in ["users", "groups"]:
        raise EnvironmentVariableInvalidError(
            variable, library_prefix, 'Must be either "users" or "groups"'
        )

    variable = "ZOTERO_API_KEY"
    api_key = os.getenv(variable)
    if not api_key:
        raise EnvironmentVariableRequiredError(variable)

    return library_id, library_prefix, api_key


@click.group()
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug messages.",
)
def cli(debug: bool) -> None:
    """Mirror a Zotero library into a SQL database."""
    load_dotenv()
    setup_logging(debug)


@cli.command(context_settings={"show_default": True})
def init() -> None:
    """Initialize the mirror database (create the tables)."""
    try:
        library_id, library_prefix, api_key = get_zotero_credentials()
        database_url = get_database_credentials(library_id, library_prefix)
    except click.UsageError as exc:
        logger.error(exc)  # noqa: TRY400 (No traceback needed)
        raise click.Abort from None

    database.initialize(database_url)
    logger.info("Mirror database initialized")


@cli.command(context_settings={"show_default": True})
@click.option(
    "--files/--no-files",
    default=False,
    help="Whether to delete the file attachments from the local mirror.",
)
def clean(files: bool) -> None:
    """Clear the mirror database (drop the tables)."""
    try:
        library_id, library_prefix, api_key = get_zotero_credentials()
        database_url = get_database_credentials(library_id, library_prefix)
        data_path = get_data_path(library_id, library_prefix)
    except click.UsageError as exc:
        logger.error(exc)  # noqa: TRY400 (No traceback needed)
        raise click.Abort from None

    database.clean(database_url, data_path, files)
    logger.info("Mirror database cleared")


@cli.command(context_settings={"show_default": True})
@optgroup.group("Data options")
@optgroup.option(
    "--locale",
    multiple=True,
    default=["en-US"],
    help=(
        "Locale for labels and reference formatting.  "
        "[multiple values can be specified by repeating the option]"
    ),
)
@optgroup.option(
    "--style",
    multiple=True,
    help=(
        "Bibliographic style to format references with.  "
        "[multiple values can be specified by repeating the option]"
    ),
)
@optgroup.option(
    "--export-format",
    multiple=True,
    help=(
        "Export format to retrieve.  [multiple values can be specified by repeating the option]."
    ),
)
@optgroup.option(
    "--fulltext/--no-fulltext",
    default=False,
    help="Whether to fetch the full text content of items.",
)
@optgroup.option(
    "--files/--no-files",
    default=False,
    help="Whether to fetch the file attachments.",
)
@optgroup.option(
    "--media-type",
    multiple=True,
    help=(
        "Accepted media types. Applies only if the files option is enabled, in which case only the "
        "files whose media type matches will be fetched. "
        "If no media types are specified, all files are accepted regardless of their media type.  "
        "[multiple values can be specified by repeating the option]"
    ),
)
@optgroup.group("Process options")
@optgroup.option(
    "--full/--incremental",
    default=False,
    help=("Force a full synchronization or let an incremental synchronization."),
)
@optgroup.option(
    "--initial-batch-size",
    type=click.IntRange(min=1, max=50),
    default=50,
    help="Number of objects to fetch by key in a single request.",
)
@optgroup.option(
    "--initial-retry-wait",
    type=click.FloatRange(min=1.0, max=600.0),
    default=2.0,
    help="Initial wait time (in seconds) for exponential backoff calculation.",
)
@optgroup.option(
    "--max-errors",
    type=click.IntRange(min=1, max=25),
    default=10,
    help="Maximum number of times a failing API request can be retried.",
)
@optgroup.option(
    "--max-requests",
    type=click.IntRange(min=1, max=50),
    default=20,
    help="Maximum number of concurrent API requests at any given time.",
)
def sync(
    full: bool,
    initial_batch_size: int,
    initial_retry_wait: float,
    max_requests: int,
    max_errors: int,
    locale: tuple[str, ...],
    style: tuple[str, ...],
    export_format: tuple[str, ...],
    fulltext: bool,
    files: bool,
    media_type: tuple[str, ...],
) -> None:
    """Synchronize the mirror database with the Zotero library."""
    try:
        library_id, library_prefix, api_key = get_zotero_credentials()
        database_url = get_database_credentials(library_id, library_prefix)
        data_path = get_data_path(library_id, library_prefix)
    except click.UsageError as exc:
        logger.error(exc)  # noqa: TRY400 (No traceback needed)
        raise click.Abort from None

    # TODO: Add timer for whole process. Perhaps through a decorator that other commandes might use.

    logger.info("Mirror database synchronization started")
    if database.synchronize(
        database_url,
        data_path,
        library_id,
        library_prefix,
        api_key,
        initial_batch_size=initial_batch_size,
        initial_retry_wait=initial_retry_wait,
        max_requests=max_requests,
        max_errors=max_errors,
        full=full,
        locales=list(locale),
        styles=list(style),
        export_formats=list(export_format),
        fulltext=fulltext,
        files=files,
        media_types=list(media_type),
    ):
        logger.info("Mirror database synchronization completed")
    else:
        logger.error("Mirror database synchronization failed")
        raise click.Abort


@cli.command(context_settings={"show_default": True})
@optgroup.group("Data options")
@optgroup.option(
    "--fulltext/--no-fulltext",
    default=False,
    help="Whether to fetch the full text content of items.",
)
@optgroup.group("Process options")
@optgroup.option(
    "--full/--incremental",
    default=False,
    help="Force a full synchronization or let an incremental synchronization.",
)
@optgroup.option(
    "--initial-retry-wait",
    type=click.FloatRange(min=1.0, max=600.0),
    default=2.0,
    help="Initial wait time (in seconds) for exponential backoff calculation.",
)
@optgroup.option(
    "--max-errors",
    type=click.IntRange(min=1, max=25),
    default=10,
    help="Maximum number of attempts a given API request is allowed.",
)
@optgroup.option(
    "--max-requests",
    type=click.IntRange(min=1, max=50),
    default=20,
    help="Maximum number of concurrent API requests at any given time.",
)
def check(
    full: bool,
    initial_retry_wait: float,
    max_requests: int,
    max_errors: int,
    fulltext: bool,
) -> None:
    """Check the synchronization status of the mirror database."""
    try:
        library_id, library_prefix, api_key = get_zotero_credentials()
        database_url = get_database_credentials(library_id, library_prefix)
        data_path = get_data_path(library_id, library_prefix)
    except click.UsageError as exc:
        logger.error(exc)  # noqa: TRY400 (No traceback needed)
        raise click.Abort from None

    logger.info("Mirror database check started")
    if database.check(
        database_url,
        data_path,
        library_id,
        library_prefix,
        api_key,
        initial_retry_wait=initial_retry_wait,
        max_requests=max_requests,
        max_errors=max_errors,
        full=full,
        fulltext=fulltext,
    ):
        logger.info("Mirror database check completed")
    else:
        logger.error("Mirror database check failed")
        raise click.Abort


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
