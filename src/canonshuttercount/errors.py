"""Errors shared by protocols and the USB boundary."""


class ProtocolError(RuntimeError):
    """A reply or requested operation does not match the supported protocol."""


class TransferTimeout(TimeoutError):
    """A USB operation exceeded its deadline."""


class TransferError(OSError):
    """USB access failed; details retain the backend's original explanation."""


class ReadFailure(ProtocolError):
    """Preserve the read error together with any cleanup or verification errors."""

    def __init__(self, primary, cleanup, interrupted=False):
        self.primary = primary
        self.cleanup = cleanup
        self.interrupted = interrupted or isinstance(primary, KeyboardInterrupt)
        messages = ([str(primary) or type(primary).__name__] if primary is not None else [])
        messages.extend(str(error) or type(error).__name__ for error in cleanup)
        super().__init__("; ".join(messages))
