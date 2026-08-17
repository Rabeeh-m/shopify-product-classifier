class ClassificationError(Exception):
    """Base exception for classification failures."""


class ClassificationParseError(ClassificationError):
    """Raised when the AI model's response cannot be validated.

    This is distinct from network/API errors — the model responded but
    its output didn't match the expected schema or constraints.
    """

    def __init__(self, message, raw_response=None):
        super().__init__(message)
        self.raw_response = raw_response


class AIClientError(ClassificationError):
    """Raised on transient or permanent AI API failures after retries."""


class AITimeoutError(AIClientError):
    """Raised when the AI API call exceeds the configured timeout."""
