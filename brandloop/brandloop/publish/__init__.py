from . import dryrun, metrics
from .base import PublishError

# Channel → publisher. Every channel currently runs the dry-run adapter; replace
# an entry here when real API credentials for that channel are available.
PUBLISHERS = {
    'x': dryrun.publish,
    'linkedin': dryrun.publish,
    'instagram': dryrun.publish,
    'facebook': dryrun.publish,
    'tiktok': dryrun.publish,
    'threads': dryrun.publish,
}


def publisher_for(channel):
    return PUBLISHERS.get(channel, dryrun.publish)


__all__ = ['PUBLISHERS', 'PublishError', 'dryrun', 'metrics', 'publisher_for']
