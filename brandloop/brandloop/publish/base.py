"""Publishing adapter contract.

A publisher takes an approved Post and puts it on a channel, returning the
permalink. Real channel adapters (X, LinkedIn, Meta) implement this same
signature and are selected by channel id in PUBLISHERS.
"""


class PublishError(RuntimeError):
    """Raised when a channel refuses a post. The scheduler records and moves on."""


def publish(post, brand, config) -> dict:
    raise NotImplementedError
