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
    STATS_CSV_COLUMNS,
    ChannelCount,
    collect,
    export_stats_csv,
    fetch_subscribers,
    main,
    run_snapshot,
    store,
    targets,
    trigger_dashboard_build,
    upload_to_r2,
)

from tests.samples.telethon_stats import NETWORK_CHANNELS, SHARED_CHANNELS, full_channel

CHANNEL_ID = -1001712561448


def _client(*side_effect):
    """A Telethon client whose call returns the given responses in order."""
    client = AsyncMock()
    client.side_effect = side_effect
    return client


# --------------------------------------------------------------------------
# fetch_subscribers
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_subscribers_returns_count():
    client = _client(full_channel(1234))

    assert await fetch_subscribers(client, CHANNEL_ID) == 1234

    request = client.call_args.args[0]
    assert isinstance(request, GetFullChannelRequest)


@pytest.mark.asyncio
async def test_fetch_subscribers_waits_out_a_flood_wait_then_succeeds(caplog):
    caplog.set_level(logging.WARNING)
    client = _client(FloodWaitError(request=None), full_channel(77))

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_subscribers(client, CHANNEL_ID) == 77

    mock_sleep.assert_awaited_once()
    assert "Rate-limited" in caplog.text


@pytest.mark.asyncio
async def test_fetch_subscribers_gives_up_after_max_attempts(caplog):
    caplog.set_level(logging.ERROR)
    client = _client(*[FloodWaitError(request=None)] * MAX_ATTEMPTS)

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_subscribers(client, CHANNEL_ID) is None

    mock_sleep.assert_count == MAX_ATTEMPTS if hasattr(mock_sleep, 'assert_count') else None
    assert mock_sleep.await_count == MAX_ATTEMPTS
    assert "Giving up" in caplog.text


@pytest.mark.asyncio
async def test_fetch_subscribers_gives_up_on_a_flood_wait_longer_than_the_cap(caplog):
    """Sleeping out an hours-long wait would hold the run's lock past the next
    night's cron entry, turning one bad evening into several missing days."""
    caplog.set_level(logging.ERROR)
    client = _client(FloodWaitError(request=None, capture=MAX_FLOOD_WAIT + 1))

    with patch('bi.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        assert await fetch_subscribers(client, CHANNEL_ID) is None

    mock_sleep.assert_not_awaited()
    assert client.await_count == 1
    assert "past the" in caplog.text


@pytest.mark.asyncio
async def test_fetch_subscribers_does_not_retry_other_errors(caplog):
    """A channel we lost access to will not come back within seconds, and the
    snapshot runs again tomorrow - retrying it only slows the run down."""
    caplog.set_level(logging.ERROR)
    client = _client(RuntimeError("channel is gone"))

    assert await fetch_subscribers(client, CHANNEL_ID) is None

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
    with patch('bi.main.fetch_subscribers', AsyncMock(side_effect=[10, 20, 30])), \
         patch('bi.main.asyncio.sleep', new_callable=AsyncMock):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert counts == [
        ChannelCount('kyiv', NETWORK_CHANNELS['kyiv'], 10),
        ChannelCount('lviv', NETWORK_CHANNELS['lviv'], 20),
        ChannelCount('odesa', NETWORK_CHANNELS['odesa'], 30),
    ]


@pytest.mark.asyncio
async def test_collect_keeps_going_when_one_channel_fails():
    with patch('bi.main.fetch_subscribers', AsyncMock(side_effect=[10, None, 30])), \
         patch('bi.main.asyncio.sleep', new_callable=AsyncMock):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert [c.channel_key for c in counts] == ['kyiv', 'odesa']


@pytest.mark.asyncio
async def test_collect_paces_its_requests():
    with patch('bi.main.fetch_subscribers', AsyncMock(return_value=1)), \
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
    assert "INSERT INTO subscribers" in sql
    assert [(r[0], r[1], r[2]) for r in rows] == [('kyiv', 111, 10), ('lviv', 222, 20)]
    assert all(isinstance(r[3], datetime.date) for r in rows)
    assert all(isinstance(r[4], datetime.datetime) for r in rows)


@pytest.mark.asyncio
async def test_store_overwrites_the_same_run_instead_of_duplicating(bi_pool):
    """The UNIQUE (channel_key, collected_at) constraint plus DO UPDATE is what makes a
    re-run safe."""
    pool, conn = bi_pool

    await store(pool, [ChannelCount('kyiv', 111, 10)])

    sql = conn.executemany.await_args.args[0]
    assert "ON CONFLICT (channel_key, collected_at) DO UPDATE" in sql


# --------------------------------------------------------------------------
# export_stats_csv
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_stats_csv_writes_a_header_row(bi_pool):
    pool, conn = bi_pool
    conn.fetch.return_value = []

    csv_text = await export_stats_csv(pool)

    assert csv_text == "channel_key,display_name,date,subscribers\n"
    assert tuple(csv_text.splitlines()[0].split(',')) == STATS_CSV_COLUMNS


@pytest.mark.asyncio
async def test_export_stats_csv_resolves_city_display_names(bi_pool):
    pool, conn = bi_pool
    conn.fetch.return_value = [
        {'channel_key': 'kryvyirih', 'collected_at': datetime.datetime(2026, 8, 14, 4, 0, 0), 'subscribers': 4321},
        {'channel_key': 'kyiv', 'collected_at': datetime.datetime(2026, 8, 15, 8, 0, 0), 'subscribers': 1234},
    ]

    rows = (await export_stats_csv(pool)).splitlines()

    assert rows[1] == "kryvyirih,Kryvyi Rih,2026-08-14 04:00:00,4321"
    assert rows[2] == "kyiv,Kyiv,2026-08-15 08:00:00,1234"


@pytest.mark.asyncio
async def test_export_stats_csv_falls_back_to_date_when_collected_at_missing(bi_pool):
    pool, conn = bi_pool
    conn.fetch.return_value = [
        {'channel_key': 'kyiv', 'date': datetime.date(2026, 8, 15), 'subscribers': 1234},
    ]

    rows = (await export_stats_csv(pool)).splitlines()
    assert rows[1] == "kyiv,Kyiv,2026-08-15,1234"


@pytest.mark.asyncio
async def test_export_stats_csv_falls_back_to_the_key_for_unknown_channels(bi_pool):
    pool, conn = bi_pool
    conn.fetch.return_value = [
        {'channel_key': 'retired', 'collected_at': '2026-08-15 12:00:00', 'subscribers': 7}
    ]

    rows = (await export_stats_csv(pool)).splitlines()
    assert rows[1] == "retired,retired,2026-08-15 12:00:00,7"


@pytest.mark.asyncio
async def test_export_stats_csv_reads_the_table_in_chronological_order(bi_pool):
    pool, conn = bi_pool
    conn.fetch.return_value = []

    await export_stats_csv(pool)

    sql = conn.fetch.call_args.args[0]
    assert "FROM subscribers" in sql
    assert "ORDER BY collected_at, channel_key" in sql


# --------------------------------------------------------------------------
# upload_to_r2
# --------------------------------------------------------------------------

def test_upload_to_r2_uploads_file_when_credentials_set(monkeypatch):
    monkeypatch.setattr(bi_main, "R2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setattr(bi_main, "R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(bi_main, "CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(bi_main, "R2_DATA_BUCKET", "sirens-bi-data")
    monkeypatch.setattr(bi_main, "R2_BUCKET", "sirens-bi-data")
    monkeypatch.setattr(bi_main, "R2_ENDPOINT", "https://test.r2.cloudflarestorage.com")

    with patch('bi.main.boto3.client') as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        upload_to_r2("channel_key,display_name\nkyiv,Kyiv\n")

    mock_boto.assert_called_once_with(
        "s3",
        endpoint_url="https://test.r2.cloudflarestorage.com",
        aws_access_key_id="test-key-id",
        aws_secret_access_key="test-secret",
        region_name="auto",
    )
    mock_s3.put_object.assert_called_once_with(
        Bucket="sirens-bi-data",
        Key="subscribers.csv",
        Body=b"channel_key,display_name\nkyiv,Kyiv\n",
        ContentType="text/csv; charset=utf-8",
    )




def test_upload_to_r2_skips_when_credentials_missing(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(bi_main, "R2_ACCESS_KEY_ID", "")

    with patch('bi.main.boto3.client') as mock_boto:
        upload_to_r2("sample csv")

    mock_boto.assert_not_called()
    assert "R2 credentials not set" in caplog.text


# --------------------------------------------------------------------------
# trigger_dashboard_build
# --------------------------------------------------------------------------

def test_trigger_dashboard_build_dispatches_when_pat_set(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(bi_main, "GITHUB_PAT", "ghp_test123")
    monkeypatch.setattr(bi_main, "GITHUB_REPO", "owner/repo")

    with patch('bi.main.requests.post') as mock_post:
        mock_post.return_value.status_code = 204
        trigger_dashboard_build()

    mock_post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/actions/workflows/dashboard.yml/dispatches",
        headers={
            "Authorization": "Bearer ghp_test123",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": "main"},
        timeout=15,
    )
    assert "Triggered GitHub Actions dashboard workflow" in caplog.text


def test_trigger_dashboard_build_handles_failed_status(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(bi_main, "GITHUB_PAT", "ghp_test123")
    monkeypatch.setattr(bi_main, "GITHUB_REPO", "owner/repo")

    with patch('bi.main.requests.post') as mock_post:
        mock_post.return_value.status_code = 404
        mock_post.return_value.text = "Not Found"
        trigger_dashboard_build()

    assert "Failed to trigger dashboard workflow (HTTP 404)" in caplog.text


def test_trigger_dashboard_build_handles_exception(monkeypatch, caplog):
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(bi_main, "GITHUB_PAT", "ghp_test123")
    monkeypatch.setattr(bi_main, "GITHUB_REPO", "owner/repo")

    with patch('bi.main.requests.post', side_effect=Exception("network down")):
        trigger_dashboard_build()

    assert "Exception while triggering GitHub Actions dashboard workflow" in caplog.text


def test_trigger_dashboard_build_skips_when_pat_missing(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(bi_main, "GITHUB_PAT", "")

    with patch('bi.main.requests.post') as mock_post:
        trigger_dashboard_build()

    mock_post.assert_not_called()
    assert "GITHUB_PAT or GITHUB_REPO not set" in caplog.text


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
         patch('bi.main.store', new_callable=AsyncMock) as mock_store, \
         patch('bi.main.export_stats_csv', AsyncMock(return_value="csv_content")) as mock_export, \
         patch('bi.main.upload_to_r2') as mock_upload, \
         patch('bi.main.trigger_dashboard_build') as mock_trigger:
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 0

    mock_store.assert_awaited_once_with(pool, counts)
    mock_export.assert_awaited_once_with(pool)
    mock_upload.assert_called_once_with("csv_content")
    mock_trigger.assert_called_once_with()
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
