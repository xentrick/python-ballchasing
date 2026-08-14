"""Rate limiter behaviour.

The bug these guard against: configure_limiter used to build
``AsyncLimiter(rps, 1)``, a token bucket that grants a full burst. That can
emit ``rps`` requests at the end of one refill window and ``rps`` more at the
start of the next -- up to ``2 * rps`` inside a *sliding* second, which is what
ballchasing measures. It also overwrote max_connections with the rate, so the
connection pool silently throttled throughput to ``rate / latency``.
"""

import asyncio

import pytest
from aiolimiter import AsyncLimiter
from payloads import ping_payload

import ballchasing
from ballchasing.api import DEFAULT_MAX_CONNECTION, MIN_REQUESTS_PER_SECOND
from ballchasing.enums import PatreonType


def peak_in_sliding_window(stamps, window=1.0):
    """Most requests landing inside any `window`-second span."""
    ordered = sorted(stamps)
    return max(
        (sum(1 for s in ordered[i:] if s - t < window) for i, t in enumerate(ordered)),
        default=0,
    )


class TestRateDerivation:
    def test_uses_documented_ceiling_with_safety_margin(self):
        api = ballchasing.Api(
            auth_key="k", patreon_type=PatreonType.ORG, rate_limit_safety=0.9
        )
        assert PatreonType.ORG.requests_per_second() == 16.0
        assert api.requests_per_second == pytest.approx(14.4)

    @pytest.mark.parametrize(
        ("tier", "expected"),
        [
            (PatreonType.REGULAR, 2.0),
            (PatreonType.GOLD, 2.0),
            (PatreonType.DIAMOND, 4.0),
            (PatreonType.CHAMPION, 8.0),
            (PatreonType.GC, 16.0),
            (PatreonType.LEGEND, 16.0),
            (PatreonType.ORG, 16.0),
        ],
    )
    def test_tier_ceilings(self, tier, expected):
        assert tier.requests_per_second() == expected
        # The deprecated alias stays consistent with the new accessor.
        assert tier.rate_limit() == pytest.approx(1 / expected)

    def test_safety_margin_scales_the_rate(self):
        full = ballchasing.Api(
            auth_key="k", patreon_type=PatreonType.ORG, rate_limit_safety=1.0
        )
        half = ballchasing.Api(
            auth_key="k", patreon_type=PatreonType.ORG, rate_limit_safety=0.5
        )
        assert full.requests_per_second == pytest.approx(16.0)
        assert half.requests_per_second == pytest.approx(8.0)

    def test_rate_never_reaches_zero(self):
        api = ballchasing.Api(auth_key="k", rate_limit_safety=0.0)
        assert api.requests_per_second == MIN_REQUESTS_PER_SECOND


class TestLimiterShape:
    def test_limiter_is_smoothed_not_bursty(self):
        """One token per 1/rps seconds, rather than rps tokens per second."""
        api = ballchasing.Api(auth_key="k", patreon_type=PatreonType.ORG)

        assert api.limiter.max_rate == 1
        assert api.limiter.time_period == pytest.approx(1 / api.requests_per_second)

    def test_max_connections_is_not_clobbered_by_the_rate(self):
        """The pool bound is a separate dimension from requests per second."""
        api = ballchasing.Api(
            auth_key="k", patreon_type=PatreonType.ORG, max_connections=64
        )
        api.configure_limiter()
        assert api.max_connections == 64

    def test_max_connections_defaults_above_any_tier_rate(self):
        api = ballchasing.Api(auth_key="k", patreon_type=PatreonType.ORG)
        assert api.max_connections == DEFAULT_MAX_CONNECTION
        assert api.max_connections > api.requests_per_second

    def test_reconfiguring_with_no_change_keeps_the_same_limiter(self):
        """Swapping in an equivalent limiter would briefly double the rate."""
        api = ballchasing.Api(auth_key="k", patreon_type=PatreonType.ORG)
        first = api.limiter
        api.configure_limiter()
        assert api.limiter is first

    def test_changing_tier_rebuilds_the_limiter(self):
        api = ballchasing.Api(auth_key="k", patreon_type=PatreonType.REGULAR)
        first = api.limiter
        api.patreon_type = PatreonType.ORG
        api.configure_limiter()

        assert api.limiter is not first
        assert api.limiter.time_period == pytest.approx(1 / api.requests_per_second)


class TestSharedLimiter:
    def test_injected_limiter_is_used(self):
        shared = AsyncLimiter(1, 0.25)
        api = ballchasing.Api(auth_key="k", limiter=shared)
        assert api.limiter is shared

    def test_injected_limiter_survives_reconfiguration(self):
        """Instances sharing an account must keep sharing one limiter."""
        shared = AsyncLimiter(1, 0.25)
        first = ballchasing.Api(auth_key="k", limiter=shared)
        second = ballchasing.Api(
            auth_key="k", patreon_type=PatreonType.ORG, limiter=shared
        )

        first.patreon_type = PatreonType.ORG
        first.configure_limiter()
        second.configure_limiter()

        assert first.limiter is shared
        assert second.limiter is shared


class TestPingUpdatesRate:
    async def test_ping_adopts_the_reported_tier(self, api, server):
        server.enqueue(payload=ping_payload(patreon_type="org"))
        assert api.patreon_type == PatreonType.REGULAR

        await api.ping()

        assert api.patreon_type == PatreonType.ORG
        assert api.requests_per_second == pytest.approx(14.4)
        assert api.limiter.time_period == pytest.approx(1 / 14.4)

    async def test_ping_does_not_override_an_explicit_sleep_time(self, server):
        async with ballchasing.Api(
            auth_key="k", base_url=server.url, sleep_time_on_rate_limit=7.5
        ) as bc:
            server.enqueue(payload=ping_payload(patreon_type="org"))
            await bc.ping()
            assert bc.sleep_time_on_rate_limit == 7.5

    async def test_ping_refreshes_the_derived_sleep_time(self, api, server):
        server.enqueue(payload=ping_payload(patreon_type="org"))
        await api.ping()
        assert api.sleep_time_on_rate_limit == pytest.approx(1 / 14.4)


class TestObservedRate:
    """Timing checks against the fake server, measured the way ballchasing would."""

    async def test_never_exceeds_the_target_in_a_sliding_second(self, server):
        async with ballchasing.Api(
            auth_key="k", base_url=server.url, patreon_type=PatreonType.ORG
        ) as bc:
            target = bc.requests_per_second
            server.set_default(payload={})

            await asyncio.gather(*(bc.get_maps() for _ in range(40)))

            peak = peak_in_sliding_window([r.received_at for r in server.requests])

        # The old bursty limiter peaked near 2x. Allow a little slack for
        # integer counting at the window edges, but nothing like a doubling.
        assert peak <= target * 1.35, (
            f"peak {peak} in a sliding second against a target of {target}"
        )

    async def test_slow_responses_do_not_throttle_the_send_rate(self, server):
        """The pool used to be capped at the rate, making throughput rate/latency."""
        latency = 0.3
        async with ballchasing.Api(
            auth_key="k", base_url=server.url, patreon_type=PatreonType.ORG
        ) as bc:
            target = bc.requests_per_second
            server.set_default(payload={}, latency=latency)

            await asyncio.gather(*(bc.get_maps() for _ in range(30)))

            stamps = sorted(r.received_at for r in server.requests)

        span = stamps[-1] - stamps[0]
        arrival_rate = (len(stamps) - 1) / span
        # Before the fix this collapsed to target/latency.
        assert arrival_rate > target * 0.7, (
            f"arrival rate {arrival_rate:.2f}/s fell well under target {target}/s"
        )
