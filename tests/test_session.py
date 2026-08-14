"""Session lifecycle.

Api() used to build a TCPConnector in __init__, which requires a running event
loop. That made the client unconstructible from synchronous code (a bare REPL,
module scope) and permanently bound the session to whichever loop happened to
be running at the time.
"""

import asyncio
import warnings

import pytest
from payloads import ping_payload

import ballchasing


class TestConstruction:
    def test_constructs_without_a_running_event_loop(self):
        """The original failure: RuntimeError: no running event loop."""
        api = ballchasing.Api(auth_key="k", patreon_type=ballchasing.PatreonType.ORG)

        assert api._session is None
        assert api.connector is None

    def test_constructing_without_use_leaks_nothing(self):
        """An unused client must not leave an unclosed connector behind."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            ballchasing.Api(auth_key="k")

    def test_repr_does_not_require_a_session(self):
        api = ballchasing.Api(auth_key="k", patreon_type=ballchasing.PatreonType.ORG)
        assert "BallchasingApi" in str(api)


class TestLazyCreation:
    async def test_session_is_created_on_first_request(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        assert api._session is None

        server.enqueue(payload={})
        await api.get_maps()

        assert api._session is not None
        await api.close()

    async def test_same_loop_reuses_one_session(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        first = await api._ensure_session()
        second = await api._ensure_session()

        assert first is second
        await api.close()

    async def test_session_is_bound_to_the_creating_loop(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        await api._ensure_session()

        assert api._session_loop is asyncio.get_running_loop()
        await api.close()


class TestCrossLoopUse:
    def test_rebuilds_when_used_on_a_different_loop(self, caplog):
        """An Api reused across asyncio.run() calls must not break."""
        api = ballchasing.Api(auth_key="k")
        seen = []

        async def touch():
            seen.append(await api._ensure_session())

        with warnings.catch_warnings():
            # The abandoned session cannot be awaited closed from a dead loop.
            warnings.simplefilter("ignore", ResourceWarning)
            asyncio.run(touch())
            with caplog.at_level("WARNING", logger="ballchasing"):
                asyncio.run(touch())

        assert seen[0] is not seen[1], "expected a rebuilt session on the new loop"
        assert "different event loop" in caplog.text


class TestClose:
    async def test_close_is_idempotent(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        await api._ensure_session()

        await api.close()
        await api.close()

        assert api._session is None
        assert api.connector is None

    async def test_close_on_a_never_used_client_is_a_noop(self):
        api = ballchasing.Api(auth_key="k")
        await api.close()
        assert api._session is None

    async def test_session_rebuilds_after_close(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        first = await api._ensure_session()
        await api.close()
        second = await api._ensure_session()

        assert second is not first
        assert not second.closed
        await api.close()

    async def test_async_context_manager_closes_the_session(self, server):
        async with ballchasing.Api(auth_key="k", base_url=server.url) as api:
            session = await api._ensure_session()
            assert not session.closed

        assert session.closed
        assert api._session is None

    async def test_context_manager_closes_on_exception(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        with pytest.raises(RuntimeError, match="boom"):
            async with api:
                await api._ensure_session()
                raise RuntimeError("boom")

        assert api._session is None


class TestReconfigure:
    async def test_reconfigure_discards_the_session(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        first = await api._ensure_session()

        await api.reconfigure_session()

        assert api._session is None
        assert first.closed
        await api.close()

    async def test_create_pings_then_reconfigures(self, server):
        server.enqueue(payload=ping_payload(patreon_type="org"))
        api = await ballchasing.Api.create(auth_key="k", base_url=server.url)
        try:
            assert api.patreon_type == ballchasing.PatreonType.ORG
            # ping() consumed the first session; reconfigure_session() dropped it.
            assert api._session is None
            assert server.paths() == ["/"]
        finally:
            await api.close()

    async def test_requests_survive_a_reconfigure(self, server):
        api = ballchasing.Api(auth_key="k", base_url=server.url)
        server.set_default(payload={})

        await api.get_maps()
        await api.reconfigure_session()
        await api.get_maps()

        assert server.call_count == 2
        await api.close()


class TestAuthHeader:
    async def test_auth_key_is_sent(self, server):
        server.set_default(payload={})
        async with ballchasing.Api(auth_key="secret-key", base_url=server.url) as api:
            await api.get_maps()

        assert server.requests[0].headers["Authorization"] == "secret-key"
