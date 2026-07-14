"""Exception hierarchy and process exit codes for the scan controller.

Exit codes mirror the MVP spec (§29). Every deliberately-raised controller
error carries the exit code the CLI should terminate with, so ``scan.py`` can
translate an exception straight into a ``SystemExit`` without a lookup table.
"""

from __future__ import annotations

# --- Exit codes (spec §29) ------------------------------------------------- #
EXIT_SUCCESS = 0
EXIT_RUNTIME = 1
EXIT_CONFIG = 2  # invalid arguments or configuration
EXIT_PREFLIGHT = 3
EXIT_CAMERA = 4
EXIT_TURNTABLE = 5
EXIT_VERIFICATION = 6  # image verification failure
EXIT_PACKAGING = 7
EXIT_INTERRUPTED = 8  # interrupted, session resumable
EXIT_TURNTABLE_UNKNOWN = 9


class ScanError(Exception):
    """Base class for all controller errors. Carries a process exit code."""

    exit_code = EXIT_RUNTIME

    def __init__(self, message: str, *, exit_code: int | None = None):
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ConfigError(ScanError):
    """Invalid CLI arguments, config file, or environment (missing token)."""

    exit_code = EXIT_CONFIG


class PreflightError(ScanError):
    """A preflight check failed before any capture or movement happened."""

    exit_code = EXIT_PREFLIGHT


class CameraError(ScanError):
    """ScannerCam was unreachable or rejected a request.

    ``retryable`` distinguishes transient faults (timeout, 5xx, connection
    reset) from terminal ones (auth, missing locks, invalid project). The
    retry loop in the session consults it before backing off (spec §20).
    """

    exit_code = EXIT_CAMERA

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        code: str | None = None,
        status: int | None = None,
        exit_code: int | None = None,
    ):
        super().__init__(message, exit_code=exit_code)
        self.retryable = retryable
        self.code = code  # machine-readable ScannerCam error code, if any
        self.status = status  # HTTP status, if any


class TurntableError(ScanError):
    """The Arduino/IR turntable was unavailable or misbehaved."""

    exit_code = EXIT_TURNTABLE


class TurntableStateUnknown(ScanError):
    """The turntable's physical state can no longer be assumed.

    Raised when a toggle may or may not have been received (crash mid-move,
    serial failure, interrupt while running). The controller must never auto-
    toggle out of this state — it requires manual intervention (spec §4, §19).
    """

    exit_code = EXIT_TURNTABLE_UNKNOWN


class VerificationError(ScanError):
    """A downloaded image failed integrity verification (spec §15, §23)."""

    exit_code = EXIT_VERIFICATION


class PackagingError(ScanError):
    """Final validation or archive creation failed (spec §23, §24)."""

    exit_code = EXIT_PACKAGING


class InterruptedResumable(ScanError):
    """The session was interrupted cleanly and can be resumed (spec §19)."""

    exit_code = EXIT_INTERRUPTED
