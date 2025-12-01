from karboni.exceptions import LibraryVersionChangeError
from karboni.typing import VersionType


class Delta:
    """Describes the version change of an ongoing synchronization."""

    def __init__(self, since: VersionType = 0):
        self._since: VersionType = since
        self._target: VersionType = 0

    def is_incremental_sync(self) -> bool:
        return self._since > 0

    @property
    def since(self) -> VersionType:
        """Version to start synchronizing from."""
        return self._since

    @property
    def target(self) -> VersionType:
        """Target version to synchronize to."""
        return self._target

    def update_target(self, last_modified_version: VersionType) -> None:
        """
        Update the target version to synchronized to.

        On the first time this is called, we just store the last modified
        version as the new synchronization target. On subsequent calls, if the
        last modified version changes, raise a VersionChangeError.
        """
        # TODO: Make implementation cleaner, without this validation + side-effect combo?
        if last_modified_version == 0:
            return  # No new version.
        if self._target == 0:
            # First time updating the version; just store it.
            self._target = last_modified_version
        elif last_modified_version != self._target:
            # The version changed during synchronization; raise an error.
            raise LibraryVersionChangeError
