"""Telethon doubles for the subscriber snapshot.

GetFullChannelRequest answers with a deep object graph; the snapshot reads
exactly one field off it, so these stubs only build the path it walks.
"""

from types import SimpleNamespace


def full_channel(participants_count):
    """The shape of a GetFullChannelRequest response, as far as bi.main cares."""
    return SimpleNamespace(full_chat=SimpleNamespace(participants_count=participants_count))


NETWORK_CHANNELS = {
    "kyiv": -1001712561448,
    "lviv": -1001703250824,
    "odesa": -1001337824256,
}

SHARED_CHANNELS = {
    "kyiv": -1001754447620,
    "lviv": -1001754447620,
    "odesa": -1001754447620,
}
