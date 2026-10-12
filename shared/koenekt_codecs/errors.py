class ConversionError(Exception):
    """A recording could not be converted. The message is shown to the user."""


class UnsupportedRecording(ConversionError):
    """The file is a variant the parser does not understand. Nothing is guessed."""


class Cancelled(Exception):
    """The user stopped the conversion."""
