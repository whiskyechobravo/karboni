from abc import ABC, abstractmethod
from typing import Any


class ReadOnlyError(RuntimeError):
    """Raised when attempting to perform a write operation in read-only mode."""

    def __str__(self) -> str:
        return "Cannot perform operation in read-only mode"


class SyncError(Exception, ABC):
    """The base class for Zotero API-related exceptions."""


class DatabaseNotInitializedError(SyncError):
    def __init__(self, database_url: str):
        self.database_url = database_url

    def __str__(self) -> str:
        return f"The database at {self.database_url} has not been initialized"


class LibraryPrefixError(SyncError):
    def __str__(self) -> str:
        return 'Library prefix must be either "users" or "groups"'


class LibraryAlreadyInSyncError(SyncError):
    def __str__(self) -> str:
        return "The Zotero library is already up-to-date"


class LibraryVersionChangeError(SyncError):
    def __str__(self) -> str:
        return "The Zotero library version changed during synchronization"


class TooManyFailuresError(SyncError):
    def __init__(self, count: int) -> None:
        self.count = count

    def __str__(self) -> str:
        return f"Failed {self.count} times on a Zotero API request"


class BatchSizeError(SyncError):
    def __init__(self, wait: float) -> None:
        self.wait = wait  # Delay to apply before retrying with a smaller batch size.

    def __str__(self) -> str:
        return "The batch size is likely too large for the Zotero API"


class SkippedError(SyncError, ABC):
    """The base class for exceptions that indicate that a request was skipped."""


class FileError(SkippedError, ABC):
    def __init__(self, item_key: str, cause: Exception | None = None) -> None:
        self.item_key = item_key
        self.cause = cause

    @abstractmethod
    def main_message(self) -> str:
        pass

    def __str__(self) -> str:
        message = self.main_message()
        if self.cause:
            message += f". {self.cause}"
        return message


class FileAlreadyInSyncError(FileError):
    def main_message(self) -> str:
        return f"File attachment {self.item_key} is already up-to-date"


class FileIntegrityError(FileError):
    def main_message(self) -> str:
        return f"File attachment {self.item_key} has an unexpected MD5 checksum"


class FileDecompressionError(FileError):
    def main_message(self) -> str:
        return f"File attachment {self.item_key} could not be decompressed"


class FileWriteError(FileError):
    def main_message(self) -> str:
        return f"File attachment {self.item_key} could not be saved"


class UsageError(Exception, ABC):
    """The base class for usage-related exceptions."""


class IncrementalSyncStatusError(UsageError):
    def __str__(self) -> str:
        return "Could not find the previous sync history to perform an incremental sync"


class IncrementalSyncInconsistencyError(UsageError):
    def __init__(self, option_name: str, previous_value: Any, current_value: Any) -> None:
        self.option_name = option_name
        self.previous_value = previous_value
        self.current_value = current_value

    def __str__(self) -> str:
        return (
            f"Incremental sync requires the {self.option_name} parameter to have the same "
            f"value as on the previous sync. Please retry with {self.option_name} set to "
            f"{self.previous_value} instead of {self.current_value}, or run a full sync"
        )
