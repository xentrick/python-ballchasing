"""Offline test harness.

Every test runs against an in-process aiohttp server bound to loopback. No
test ever contacts ballchasing.com, and no real API key is involved -- see the
``block_real_ballchasing`` autouse fixture, which makes the default base URL
unroutable so a mistakenly default-constructed Api fails fast instead of
reaching production.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web

import ballchasing

# Any request here fails to connect immediately rather than escaping the host.
UNROUTABLE_URL = "http://127.0.0.1:1"


@pytest.fixture(autouse=True)
def block_real_ballchasing(monkeypatch):
    """Make the production base URL unusable for the whole test session."""
    monkeypatch.setattr(ballchasing.api, "DEFAULT_URL", UNROUTABLE_URL)


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str]
    # Repeated keys (player-id, playlist, ...) collapse in `query`, so keep the
    # full ordered list too.
    query_pairs: list[tuple[str, str]]
    headers: dict[str, str]
    body: bytes
    received_at: float


@dataclass
class CannedResponse:
    status: int = 200
    payload: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    latency: float = 0.0


class FakeBallchasing:
    """Records what the client sent and replays canned responses in order."""

    def __init__(self):
        self.requests: list[RecordedRequest] = []
        self._queue: deque[CannedResponse] = deque()
        self.default = CannedResponse()
        self.url = ""

    def enqueue(self, status=200, payload=None, headers=None, latency=0.0, times=1):
        """Queue a response. Consumed in order, one per request."""
        for _ in range(times):
            self._queue.append(
                CannedResponse(
                    status=status,
                    payload={} if payload is None else payload,
                    headers=headers or {},
                    latency=latency,
                )
            )
        return self

    def set_default(self, status=200, payload=None, headers=None, latency=0.0):
        """Response used once the queue is empty."""
        self.default = CannedResponse(
            status=status,
            payload={} if payload is None else payload,
            headers=headers or {},
            latency=latency,
        )
        return self

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def paths(self) -> list[str]:
        return [r.path for r in self.requests]

    async def _handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=request.path,
                query=dict(request.query),
                query_pairs=list(request.query.items()),
                headers=dict(request.headers),
                body=await request.read(),
                received_at=time.monotonic(),
            )
        )
        canned = self._queue.popleft() if self._queue else self.default
        if canned.latency:
            await asyncio.sleep(canned.latency)
        if isinstance(canned.payload, bytes):
            return web.Response(
                body=canned.payload, status=canned.status, headers=canned.headers
            )
        return web.json_response(
            canned.payload, status=canned.status, headers=canned.headers
        )


@pytest.fixture()
async def server():
    """A loopback stand-in for ballchasing.com."""
    fake = FakeBallchasing()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake._handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # site.name resolves the ephemeral port picked by binding to 0.
    fake.url = site.name.rstrip("/")

    try:
        yield fake
    finally:
        await runner.cleanup()


@pytest.fixture()
async def api(server):
    """An Api wired to the fake server, with sleeps left intact."""
    async with ballchasing.Api(auth_key="test-key", base_url=server.url) as bc:
        yield bc


@pytest.fixture()
async def fast_api(server, monkeypatch):
    """Like `api`, but asyncio.sleep is a no-op so backoff tests run instantly."""

    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr("ballchasing.api.asyncio.sleep", instant_sleep)
    async with ballchasing.Api(
        auth_key="test-key", base_url=server.url, sleep_time_on_rate_limit=0.1
    ) as bc:
        yield bc
