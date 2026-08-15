import datetime
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

from bi import main as bi_main
from bi.main import (
    MAX_ATTEMPTS,
    MAX_FLOOD_WAIT,
    ChannelCount,
    collect,
    fetch_participants,
    main,
    run_snapshot,
    store,
    targets,
)
from tests.samples.telethon_stats import NETWORK_CHANNELS, SHARED_CHANNELS, full_channel

CHANNEL_ID = -1001712561448


def _client(*side_effect):
    """A Telethon client whose call returns the given responses in order."""
    client = AsyncMock()
    client.side_effect = side_effect
    return client


# --------------------------------------------------------------------------
# fetch_participants
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_participants_returns_count():
    client = _client(full_channel(1234))

    assert await fetch_participants(client, CHANNEL_ID) == 1234

    request = client.call_args.args[0]
    assert isinstance(request, GetFullChannelRequest)


@pytest.mark.asyncio
async def test_fetch_participants_waits_out_a_flood_wait_then_succeeds(caplog):
    caplog.set_level(logging.WARNING)
    client = _client(FloodWaitError(request=None), full_channel(77))

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_participants(client, CHANNEL_ID) == 77

    mock_sleep.assert_awaited_once()
    assert "Rate-limited" in caplog.text


@pytest.mark.asyncio
async def test_fetch_participants_gives_up_after_max_attempts(caplog):
    caplog.set_level(logging.ERROR)
    client = _client(*[FloodWaitError(request=None)] * MAX_ATTEMPTS)

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_participants(client, CHANNEL_ID) is None

    assert mock_sleep.await_count == MAX_ATTEMPTS
    assert "Giving up" in caplog.text


@pytest.mark.asyncio
async def test_fetch_participants_gives_up_on_a_flood_wait_longer_than_the_cap(caplog):
    """Sleeping out an hours-long wait would hold the run's lock past the next
    night's cron entry, turning one bad evening into several missing days."""
    caplog.set_level(logging.ERROR)
    client = _client(FloodWaitError(request=None, capture=MAX_FLOOD_WAIT + 1))

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_participants(client, CHANNEL_ID) is None

    mock_sleep.assert_not_awaited()
    assert client.await_count == 1
    assert "past the" in caplog.text


@pytest.mark.asyncio
async def test_fetch_participants_does_not_retry_other_errors(caplog):
    """A channel we lost access to will not come back within seconds, and the
    snapshot runs again tomorrow - retrying it only slows the run down."""
    caplog.set_level(logging.ERROR)
    client = _client(RuntimeError("channel is gone"))

    assert await fetch_participants(client, CHANNEL_ID) is None

    assert client.await_count == 1
    assert "Failed to read subscriber count" in caplog.text


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------

def test_targets_lists_every_network_channel():
    assert targets(NETWORK_CHANNELS) == [
        ('kyiv', NETWORK_CHANNELS['kyiv']),
        ('lviv', NETWORK_CHANNELS['lviv']),
        ('odesa', NETWORK_CHANNELS['odesa']),
    ]


def test_targets_drops_the_foreign_source_channel():
    assert 'source' not in [key for key, _ in targets(NETWORK_CHANNELS)]


def test_targets_counts_a_shared_channel_once():
    assert targets(SHARED_CHANNELS) == [('kyiv', SHARED_CHANNELS['kyiv'])]


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_counts_every_network_channel():
    with patch('bi.main.fetch_participants', AsyncMock(side_effect=[10, 20, 30])), \
         patch('bi.main.asyncio.sleep', new_callable=AsyncMock):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert counts == [
        ChannelCount('kyiv', NETWORK_CHANNELS['kyiv'], 10),
        ChannelCount('lviv', NETWORK_CHANNELS['lviv'], 20),
        ChannelCount('odesa', NETWORK_CHANNELS['odesa'], 30),
    ]


@pytest.mark.asyncio
async def test_collect_keeps_going_when_one_channel_fails():
    with patch('bi.main.fetch_participants', AsyncMock(side_effect=[10, None, 30])), \
         patch('bi.main.asyncio.sleep', new_callable=AsyncMock):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert [c.channel_key for c in counts] == ['kyiv', 'odesa']


@pytest.mark.asyncio
async def test_collect_paces_its_requests():
    with patch('bi.main.fetch_participants', AsyncMock(return_value=1)), \
         patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        await collect(AsyncMock(), NETWORK_CHANNELS)

    assert mock_sleep.await_count == 3
    mock_sleep.assert_awaited_with(bi_main.CHANNEL_DELAY)


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_writes_one_row_per_channel(bi_pool):
    pool, conn = bi_pool
    counts = [ChannelCount('kyiv', 111, 10), ChannelCount('lviv', 222, 20)]

    await store(pool, counts)

    sql, rows = conn.executemany.await_args.args
    assert "INSERT INTO channel_stats" in sql
    assert [(r[0], r[1], r[2]) for r in rows] == [('kyiv', 111, 10), ('lviv', 222, 20)]
    assert all(isinstance(r[3], datetime.date) for r in rows)
    assert all(isinstance(r[4], datetime.datetime) for r in rows)


@pytest.mark.asyncio
async def test_store_overwrites_the_same_day_instead_of_duplicating(bi_pool):
    """The UNIQUE (channel_key, date) constraint plus DO UPDATE is what makes a
    manual re-run safe at any hour."""
    pool, conn = bi_pool

    await store(pool, [ChannelCount('kyiv', 111, 10)])

    sql = conn.executemany.await_args.args[0]
    assert "ON CONFLICT (channel_key, date) DO UPDATE" in sql


# --------------------------------------------------------------------------
# run_snapshot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_snapshot_stores_and_reports(bi_pool, caplog):
    caplog.set_level(logging.INFO)
    pool, _ = bi_pool
    counts = [
        ChannelCount('kyiv', 111, 10),
        ChannelCount('lviv', 222, 20),
        ChannelCount('odesa', 333, 30),
    ]

    with patch('bi.main.collect', AsyncMock(return_value=counts)), \
         patch('bi.main.store', new_callable=AsyncMock) as mock_store:
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 0

    mock_store.assert_awaited_once_with(pool, counts)
    assert "3/3 channels" in caplog.text
    assert "60 subscribers" in caplog.text


@pytest.mark.asyncio
async def test_run_snapshot_discards_a_run_that_missed_too_much_of_the_network(bi_pool, caplog):
    """A short day is worse than a missing one: summed across the network it
    reads as subscribers walking away, while a gap is visibly a gap."""
    caplog.set_level(logging.ERROR)
    pool, _ = bi_pool
    counts = [ChannelCount('kyiv', 111, 10), ChannelCount('lviv', 222, 20)]

    with patch('bi.main.collect', AsyncMock(return_value=counts)), \
         patch('bi.main.store', new_callable=AsyncMock) as mock_store:
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 1

    mock_store.assert_not_awaited()
    assert "reached only 2 of 3 channels" in caplog.text


@pytest.mark.asyncio
async def test_run_snapshot_fails_loudly_when_nothing_was_counted(bi_pool, caplog):
    """An empty run means the session died or Telegram is unreachable. Exiting 0
    would leave the dashboard showing yesterday's numbers as if they were today's."""
    caplog.set_level(logging.ERROR)
    pool, _ = bi_pool

    with patch('bi.main.collect', AsyncMock(return_value=[])), \
         patch('bi.main.store', new_callable=AsyncMock) as mock_store:
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 1

    mock_store.assert_not_awaited()
    assert "collected no channels" in caplog.text


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def _telegram_client(enter=None, side_effect=None):
    """Patch target for TelegramClient(...) used as an async context manager."""
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=enter or AsyncMock(), side_effect=side_effect)
    instance.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=instance)


@pytest.mark.asyncio
async def test_main_runs_the_snapshot_and_closes_the_pool(bi_pool):
    pool, _ = bi_pool
    pool.close = AsyncMock()

    with patch('bi.main.cli.get_args', return_value=MagicMock(mode='dev')), \
         patch('bi.main.sentry_sdk.init'), \
         patch('bi.main.sentry_sdk.set_tag') as mock_set_tag, \
         patch('bi.main.ensure_pg_tables') as mock_ensure, \
         patch('bi.main.asyncpg.create_pool', AsyncMock(return_value=pool)), \
         patch('bi.main.TelegramClient', _telegram_client()), \
         patch('bi.main.run_snapshot', AsyncMock(return_value=0)) as mock_run:
        assert await main() == 0

    mock_ensure.assert_called_once_with()
    mock_run.assert_awaited_once()
    pool.close.assert_awaited_once()
    mock_set_tag.assert_called_once_with("service", "bi")


@pytest.mark.asyncio
async def test_main_closes_the_pool_even_when_the_snapshot_raises(bi_pool):
    pool, _ = bi_pool
    pool.close = AsyncMock()

    with patch('bi.main.cli.get_args', return_value=MagicMock(mode='dev')), \
         patch('bi.main.sentry_sdk.init'), \
         patch('bi.main.ensure_pg_tables'), \
         patch('bi.main.asyncpg.create_pool', AsyncMock(return_value=pool)), \
         patch('bi.main.TelegramClient', _telegram_client()), \
         patch('bi.main.run_snapshot', AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await main()

    pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_reports_a_missing_session_instead_of_hanging(caplog):
    """Under cron there is no stdin, so Telethon's login prompt raises EOFError.
    That is a setup problem with a one-line fix, not a stack trace."""
    caplog.set_level(logging.ERROR)

    with patch('bi.main.cli.get_args', return_value=MagicMock(mode='prod')), \
         patch('bi.main.sentry_sdk.init'), \
         patch('bi.main.ensure_pg_tables') as mock_ensure, \
         patch('bi.main.asyncpg.create_pool', new_callable=AsyncMock) as mock_pool, \
         patch('bi.main.TelegramClient', _telegram_client(side_effect=EOFError)):
        assert await main() == 1

    mock_ensure.assert_not_called()
    mock_pool.assert_not_awaited()
    assert "./deploy/setup.sh bi" in caplog.text
