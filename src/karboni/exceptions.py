from abc import ABC
from typing import Any


class KarboniError(Exception, ABC):
    """
    Generic error.

    When raised with `raise ... from ...`, the cause of the exception will be appended to the
    message.
    """

    def __str__(self) -> str:
        message = self.get_message()
        if self.__cause__:
            message = f"{message}. {self.__cause__}"
        return message

    def get_message(self) -> str:
        """Override this method in subclasses to provide the base error message."""
        return "An error occurred"


class SyncError(KarboniError, ABC):
    """The base class for Zotero API-related exceptions."""

    def get_message(self) -> str:
        return "A synchronization error occurred"


class DatabaseNotInitializedError(SyncError):
    def __init__(self, database_url: str):
        self.database_url = database_url

    def get_message(self) -> str:
        return f"The database at {self.database_url} has not been initialized"


class LibraryPrefixError(SyncError):
    def get_message(self) -> str:
        return 'Library prefix must be either "users" or "groups"'


class LibraryAlreadyInSyncError(SyncError):
    def get_message(self) -> str:
        return "The database is already up-to-date"


class LibraryVersionChangeError(SyncError):
    def get_message(self) -> str:
        return "The Zotero library version changed during synchronization"


class TooManyFailuresError(SyncError):
    def __init__(self, count: int) -> None:
        self.count = count

    def get_message(self) -> str:
        return f"Failed {self.count} times on a Zotero API request"


class BatchSizeError(SyncError):
    def __init__(self, wait: float) -> None:
        self.wait = wait  # Delay to apply before retrying with a smaller batch size.

    def get_message(self) -> str:
        return "The batch size is likely too large for the Zotero API"


class SkippedError(SyncError, ABC):
    """The base class for exceptions that indicate that a request was skipped."""

    def get_message(self) -> str:
        return "A request was skipped"


class SkippedFileError(SkippedError, ABC):
    def __init__(self, filename: str) -> None:
        self.filename = filename

    def get_message(self) -> str:
        return f"File attachment {self.filename} has caused an error"


class SkippedFileAlreadyInSyncError(SkippedFileError):
    def get_message(self) -> str:
        return f"File attachment {self.filename} is already up-to-date"


class SkippedFileIntegrityError(SkippedFileError):
    def get_message(self) -> str:
        return f"File attachment {self.filename} has an unexpected MD5 checksum"


class SkippedFileDecompressionError(SkippedFileError):
    def get_message(self) -> str:
        return f"File attachment {self.filename} could not be decompressed"


class SkippedFileWriteError(SkippedFileError):
    def get_message(self) -> str:
        return f"File attachment {self.filename} could not be saved"


class UsageError(KarboniError, ABC):
    """The base class for usage-related exceptions."""

    def get_message(self) -> str:
        return "A usage error occurred"


class IncrementalSyncStatusError(UsageError):
    def get_message(self) -> str:
        return "Could not find the previous sync history to perform an incremental sync"


class IncrementalSyncInconsistencyError(UsageError):
    def __init__(self, option_name: str, previous_value: Any, current_value: Any) -> None:
        self.option_name = option_name
        self.previous_value = previous_value
        self.current_value = current_value

    def get_message(self) -> str:
        return (
            f"Incremental sync requires the {self.option_name} parameter to have the same "
            f"value as on the previous sync. Please retry with {self.option_name} set to "
            f"{self.previous_value} instead of {self.current_value}, or run a full sync"
        )
