"""Retry, backoff and error mapping."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from payloads import replay_payload

import ballchasing
from ballchasing.api import BACKOFF_MULTIPLIER, MAX_BACKOFF_ATTEMPTS
from ballchasing.exceptions import (
    BackoffLimitExceeded,
    BallchasingFault,
    DuplicateReplay,
    MissingAPIKey,
    UserFault,
)


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (400, UserFault),
            (401, MissingAPIKey),
            (409, DuplicateReplay),
            (500, BallchasingFault),
        ],
    )
    async def test_status_maps_to_exception(self, fast_api, server, status, expected):
        server.enqueue(status=status, payload={"error": "nope"})
        with pytest.raises(expected):
            await fast_api.get_replay("some-id")

    async def test_user_fault_carries_the_payload(self, fast_api, server):
        server.enqueue(status=400, payload={"error": "bad query"})
        with pytest.raises(UserFault) as excinfo:
            await fast_api.get_replay("some-id")
        assert "bad query" in str(excinfo.value)

    async def test_unhandled_status_raises_for_status(self, fast_api, server):
        server.enqueue(status=418, payload={})
        with pytest.raises(Exception) as excinfo:
            await fast_api.get_replay("some-id")
        assert "418" in str(excinfo.value)


class TestRateLimitRetry:
    async def test_retries_after_429_then_succeeds(self, fast_api, server):
        server.enqueue(status=429, payload={})
        server.enqueue(status=200, payload=replay_payload("abc"))

        replay = await fast_api.get_replay("abc")

        assert replay.id == "abc"
        assert server.call_count == 2

    async def test_counts_rate_limits(self, fast_api, server):
        server.enqueue(status=429, payload={}, times=3)
        server.enqueue(status=200, payload=replay_payload("abc"))

        await fast_api.get_replay("abc")

        assert fast_api.rate_limit_count == 3

    async def test_gives_up_after_the_backoff_limit(self, fast_api, server):
        server.set_default(status=429, payload={})

        with pytest.raises(BackoffLimitExceeded):
            await fast_api.get_replay("abc")

        assert server.call_count == MAX_BACKOFF_ATTEMPTS + 1


class TestBackoffDelay:
    """_backoff_delay decides how long a rate-limited caller waits."""

    def _response(self, headers=None):
        class FakeResponse:
            def __init__(self, headers):
                self.headers = headers or {}

        return FakeResponse(headers)

    def test_grows_exponentially_with_attempts(self):
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=1.0)
        response = self._response()

        for attempt in (1, 2, 3):
            base = 1.0 * (attempt**BACKOFF_MULTIPLIER)
            delay = api._backoff_delay(response, attempt)
            assert base / 2 <= delay <= base

    def test_is_jittered(self):
        """Identical waits would re-synchronise the herd that caused the 429."""
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=1.0)
        response = self._response()

        delays = {api._backoff_delay(response, 3) for _ in range(20)}
        assert len(delays) > 1

    def test_honours_retry_after_seconds(self):
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=1.0)
        response = self._response({"Retry-After": "30"})

        delay = api._backoff_delay(response, 1)
        assert 15.0 <= delay <= 30.0

    def test_honours_retry_after_http_date(self):
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=1.0)
        when = datetime.now(UTC) + timedelta(seconds=60)
        response = self._response({"Retry-After": format_datetime(when, usegmt=True)})

        delay = api._backoff_delay(response, 1)
        # Half of ~60s, allowing a second of clock drift during the test.
        assert 25.0 <= delay <= 60.0

    def test_ignores_unparseable_retry_after(self):
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=2.0)
        response = self._response({"Retry-After": "soon-ish"})

        delay = api._backoff_delay(response, 1)
        assert 1.0 <= delay <= 2.0

    def test_zero_sleep_time_disables_waiting(self):
        api = ballchasing.Api(auth_key="k", sleep_time_on_rate_limit=0.0)
        assert api._backoff_delay(self._response(), 4) == 0.0

    async def test_retry_after_is_used_by_the_request_loop(self, fast_api, server):
        server.enqueue(status=429, payload={}, headers={"Retry-After": "1"})
        server.enqueue(status=200, payload=replay_payload("abc"))

        replay = await fast_api.get_replay("abc")

        assert replay.id == "abc"
        assert server.call_count == 2


class TestRetrySafeUploads:
    """Each attempt needs its own FormData: the previous one's file handle is
    closed by the cleanup callback and cannot be replayed."""

    async def test_upload_from_bytes_rebuilds_form_data_after_429(
        self, fast_api, server
    ):
        server.enqueue(status=429, payload={})
        server.enqueue(status=201, payload={"id": "retry-id"})

        result = await fast_api.upload_replay_from_bytes(
            "retry.replay", b"replay-bytes", visibility=ballchasing.Visibility.PRIVATE
        )

        assert result.id == "retry-id"
        assert server.call_count == 2
        # Both attempts carried the file, so the body was genuinely rebuilt.
        assert all(b"replay-bytes" in r.body for r in server.requests)

    async def test_upload_from_file_rebuilds_form_data_after_429(
        self, tmp_path, fast_api, server
    ):
        replay = tmp_path / "upload.replay"
        replay.write_bytes(b"file-bytes")

        server.enqueue(status=429, payload={})
        server.enqueue(status=201, payload={"id": "upload-id"})

        result = await fast_api.upload_replay(
            str(replay), visibility=ballchasing.Visibility.PRIVATE
        )

        assert result.id == "upload-id"
        assert server.call_count == 2
        assert all(b"file-bytes" in r.body for r in server.requests)

    async def test_file_handles_are_closed_after_upload(
        self, tmp_path, fast_api, server, monkeypatch
    ):
        """A retried upload must not leak a handle per attempt."""
        replay = tmp_path / "upload.replay"
        replay.write_bytes(b"file-bytes")
        server.enqueue(status=429, payload={})
        server.enqueue(status=201, payload={"id": "upload-id"})

        real_open = open
        handles = []

        def tracking_open(file, *args, **kwargs):
            handle = real_open(file, *args, **kwargs)
            if file == str(replay):
                handles.append(handle)
            return handle

        monkeypatch.setattr("builtins.open", tracking_open)
        await fast_api.upload_replay(str(replay))
        monkeypatch.undo()

        assert len(handles) == 2, "each attempt needs its own handle"
        assert all(h.closed for h in handles)

    async def test_duplicate_replay_surfaces_on_upload(self, fast_api, server):
        server.enqueue(status=409, payload={"id": "dupe", "error": "duplicate"})

        with pytest.raises(DuplicateReplay):
            await fast_api.upload_replay_from_bytes("dupe.replay", b"bytes")
