"""
Unit tests for bi.main (subscriber statistics snapshot and export).
"""

import datetime
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

from bi.main import (
    CHANNEL_DELAY,
    MAX_ATTEMPTS,
    ChannelCount,
    collect,
    fetch_participants,
    main,
    run_snapshot,
    store,
)
from tests.samples.telethon_stats import NETWORK_CHANNELS, SHARED_CHANNELS, full_channel

CHANNEL_ID = -1001712561448


def _client(*side_effect):
    client = AsyncMock()
    client.side_effect = side_effect
    return client


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

    with patch("bi.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        assert await fetch_participants(client, CHANNEL_ID) == 77

    mock_sleep.assert_awaited_once()
    assert "Rate-limited" in caplog.text


@pytest.mark.asyncio
async def test_fetch_participants_gives_up_after_max_attempts(caplog):
    caplog.set_level(logging.ERROR)
    client = _client(*[FloodWaitError(request=None)] * MAX_ATTEMPTS)

    with patch("bi.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        assert await fetch_participants(client, CHANNEL_ID) is None

    assert mock_sleep.await_count == MAX_ATTEMPTS
    assert "Giving up" in caplog.text


@pytest.mark.asyncio
async def test_fetch_participants_does_not_retry_other_errors(caplog):
    caplog.set_level(logging.ERROR)
    client = _client(RuntimeError("channel is gone"))

    assert await fetch_participants(client, CHANNEL_ID) is None

    assert client.await_count == 1
    assert "Failed to read subscriber count" in caplog.text


@pytest.mark.asyncio
async def test_collect_counts_every_network_channel():
    with (
        patch("bi.main.fetch_subscribers", AsyncMock(side_effect=[10, 20, 30])),
        patch("bi.main.asyncio.sleep", new_callable=AsyncMock),
    ):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert counts == [
        ChannelCount("kyiv", NETWORK_CHANNELS["kyiv"], 10),
        ChannelCount("lviv", NETWORK_CHANNELS["lviv"], 20),
        ChannelCount("odesa", NETWORK_CHANNELS["odesa"], 30),
    ]


@pytest.mark.asyncio
async def test_collect_skips_the_foreign_source_channel():
    with (
        patch("bi.main.fetch_subscribers", AsyncMock(return_value=1)) as mock_fetch,
        patch("bi.main.asyncio.sleep", new_callable=AsyncMock),
    ):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    counted_ids = [call.args[1] for call in mock_fetch.await_args_list]
    assert NETWORK_CHANNELS["source"] not in counted_ids
    assert "source" not in [c.channel_key for c in counts]


@pytest.mark.asyncio
async def test_collect_counts_a_shared_channel_only_once():
    with (
        patch("bi.main.fetch_subscribers", AsyncMock(return_value=5)) as mock_fetch,
        patch("bi.main.asyncio.sleep", new_callable=AsyncMock),
    ):
        counts = await collect(AsyncMock(), SHARED_CHANNELS)

    assert mock_fetch.await_count == 1
    assert counts == [ChannelCount("kyiv", SHARED_CHANNELS["kyiv"], 5)]


@pytest.mark.asyncio
async def test_collect_keeps_going_when_one_channel_fails():
    with (
        patch("bi.main.fetch_subscribers", AsyncMock(side_effect=[10, None, 30])),
        patch("bi.main.asyncio.sleep", new_callable=AsyncMock),
    ):
        counts = await collect(AsyncMock(), NETWORK_CHANNELS)

    assert [c.channel_key for c in counts] == ["kyiv", "odesa"]


@pytest.mark.asyncio
async def test_collect_paces_its_requests():
    with (
        patch("bi.main.fetch_subscribers", AsyncMock(return_value=1)),
        patch("bi.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await collect(AsyncMock(), NETWORK_CHANNELS)

    assert mock_sleep.await_count == 3
    mock_sleep.assert_awaited_with(CHANNEL_DELAY)


@pytest.mark.asyncio
async def test_store_writes_one_row_per_channel(bi_pool):
    pool, conn = bi_pool
    counts = [ChannelCount("kyiv", 111, 10), ChannelCount("lviv", 222, 20)]

    await store(pool, counts)

    sql, rows = conn.executemany.await_args.args
    assert "INSERT INTO subscribers" in sql
    assert [(r[0], r[1], r[2]) for r in rows] == [("kyiv", 111, 10), ("lviv", 222, 20)]
    assert all(isinstance(r[3], datetime.date) for r in rows)
    assert all(isinstance(r[4], datetime.datetime) for r in rows)


@pytest.mark.asyncio
async def test_store_overwrites_the_same_day_instead_of_duplicating(bi_pool):
    pool, conn = bi_pool

    await store(pool, [ChannelCount("kyiv", 111, 10)])

    sql = conn.executemany.await_args.args[0]
    assert "ON CONFLICT (channel_key, time) DO UPDATE" in sql


@pytest.mark.asyncio
async def test_fetch_participants_skips_when_flood_wait_exceeds_cap(caplog):
    caplog.set_level(logging.ERROR)
    err = FloodWaitError(request=None, capture=600)
    err.seconds = 600
    client = _client(err)

    assert await fetch_participants(client, CHANNEL_ID) is None
    assert "past the 300s cap" in caplog.text


@pytest.mark.asyncio
async def test_run_snapshot_stores_and_reports(bi_pool, caplog):
    caplog.set_level(logging.INFO)
    pool, _ = bi_pool
    counts = [
        ChannelCount("kyiv", 111, 10),
        ChannelCount("lviv", 222, 20),
        ChannelCount("odesa", 333, 30),
    ]

    with (
        patch("bi.main.collect", AsyncMock(return_value=counts)),
        patch("bi.main.store", new_callable=AsyncMock) as mock_store,
        patch("bi.main.export_stats_csv", AsyncMock(return_value="csv_data")),
        patch("bi.main.upload_to_r2"),
        patch("bi.main.trigger_dashboard_build"),
    ):
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 0

    mock_store.assert_awaited_once_with(pool, counts)
    assert "3/3 channels" in caplog.text
    assert "60 subscribers" in caplog.text


@pytest.mark.asyncio
async def test_run_snapshot_fails_when_below_min_coverage(bi_pool, caplog):
    caplog.set_level(logging.ERROR)
    pool, _ = bi_pool
    counts = [ChannelCount("kyiv", 111, 10)]

    with (
        patch("bi.main.collect", AsyncMock(return_value=counts)),
        patch("bi.main.store", new_callable=AsyncMock) as mock_store,
    ):
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 1

    mock_store.assert_not_awaited()
    assert "discarding it rather than storing" in caplog.text


@pytest.mark.asyncio
async def test_run_snapshot_fails_loudly_when_nothing_was_counted(bi_pool, caplog):
    caplog.set_level(logging.ERROR)
    pool, _ = bi_pool

    with (
        patch("bi.main.collect", AsyncMock(return_value=[])),
        patch("bi.main.store", new_callable=AsyncMock) as mock_store,
    ):
        assert await run_snapshot(AsyncMock(), pool, NETWORK_CHANNELS) == 1

    mock_store.assert_not_awaited()
    assert "collected no channels" in caplog.text


@pytest.mark.asyncio
async def test_export_stats_csv(bi_pool):
    pool, conn = bi_pool
    now = datetime.datetime(2026, 8, 19, 12, 0, 0)
    conn.fetch.return_value = [
        {"channel_key": "kyiv", "time": now, "date": now.date(), "subscribers": 100},
        {"channel_key": "custom", "date": now.date(), "subscribers": 50},
    ]

    from bi.main import export_stats_csv

    csv_str = await export_stats_csv(pool)

    assert "channel_key,display_name,date,subscribers" in csv_str
    assert "kyiv,Kyiv,2026-08-19 12:00:00,100" in csv_str
    assert "custom,custom,2026-08-19,50" in csv_str


def test_upload_to_r2_skips_when_no_credentials(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr("bi.main.CLOUDFLARE_R2_ACCESS_KEY_ID", "")
    from bi.main import upload_to_r2

    upload_to_r2("some,csv")
    assert "R2 credentials not set" in caplog.text


def test_upload_to_r2_uploads_when_configured(monkeypatch):
    monkeypatch.setattr("bi.main.CLOUDFLARE_R2_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr("bi.main.CLOUDFLARE_R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr("bi.main.CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setattr("bi.main.CLOUDFLARE_R2_BI_DATA_BUCKET", "test-bucket")
    monkeypatch.setattr("bi.main.CLOUDFLARE_R2_S3_ENDPOINT", "https://example.com")

    with patch("bi.main.boto3.client") as mock_boto:
        s3 = MagicMock()
        mock_boto.return_value = s3
        from bi.main import upload_to_r2

        upload_to_r2("some,csv")

    s3.put_object.assert_called_once()
    kwargs = s3.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "test-bucket"
    assert kwargs["Key"] == "subscribers.csv"


def test_trigger_dashboard_build_skips_when_not_configured(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr("bi.main.GITHUB_PAT", "")
    from bi.main import trigger_dashboard_build

    trigger_dashboard_build()
    assert "GITHUB_PAT or GITHUB_REPO not set" in caplog.text


def test_trigger_dashboard_build_calls_github_api(monkeypatch):
    monkeypatch.setattr("bi.main.GITHUB_PAT", "gh-token")
    monkeypatch.setattr("bi.main.GITHUB_REPO", "owner/repo")

    with patch("bi.main.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        from bi.main import trigger_dashboard_build

        trigger_dashboard_build()

    mock_post.assert_called_once()
    assert "owner/repo/actions/workflows/dashboard.yml/dispatches" in mock_post.call_args.args[0]


def _telegram_client(enter=None, side_effect=None):
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=enter or AsyncMock(), side_effect=side_effect)
    instance.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=instance)


@pytest.mark.asyncio
async def test_main_runs_the_snapshot_and_closes_the_pool(bi_pool):
    pool, _ = bi_pool
    pool.close = AsyncMock()

    with (
        patch("bi.main.cli.get_args", return_value=MagicMock(mode="dev")),
        patch("bi.main.sentry_sdk.init"),
        patch("bi.main.sentry_sdk.set_tag") as mock_set_tag,
        patch("bi.main.ensure_pg_tables") as mock_ensure,
        patch("bi.main.asyncpg.create_pool", AsyncMock(return_value=pool)),
        patch("bi.main.TelegramClient", _telegram_client()),
        patch("bi.main.run_snapshot", AsyncMock(return_value=0)) as mock_run,
    ):
        assert await main() == 0

    mock_ensure.assert_called_once_with()
    mock_run.assert_awaited_once()
    pool.close.assert_awaited_once()
    mock_set_tag.assert_called_once_with("service", "bi")


@pytest.mark.asyncio
async def test_main_closes_the_pool_even_when_the_snapshot_raises(bi_pool):
    pool, _ = bi_pool
    pool.close = AsyncMock()

    with (
        patch("bi.main.cli.get_args", return_value=MagicMock(mode="dev")),
        patch("bi.main.sentry_sdk.init"),
        patch("bi.main.ensure_pg_tables"),
        patch("bi.main.asyncpg.create_pool", AsyncMock(return_value=pool)),
        patch("bi.main.TelegramClient", _telegram_client()),
        patch("bi.main.run_snapshot", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        with pytest.raises(RuntimeError):
            await main()

    pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_reports_a_missing_session_instead_of_hanging(caplog):
    caplog.set_level(logging.ERROR)

    with (
        patch("bi.main.cli.get_args", return_value=MagicMock(mode="prod")),
        patch("bi.main.sentry_sdk.init"),
        patch("bi.main.ensure_pg_tables") as mock_ensure,
        patch("bi.main.asyncpg.create_pool", new_callable=AsyncMock) as mock_pool,
        patch("bi.main.TelegramClient", _telegram_client(side_effect=EOFError)),
    ):
        assert await main() == 1

    mock_ensure.assert_not_called()
    mock_pool.assert_not_awaited()
    assert "./deploy/setup.sh bi" in caplog.text
