"""Endpoint behaviour: request shape in, model out."""

import json
from datetime import UTC, datetime

import pytest
from payloads import (
    group_payload,
    group_search_payload,
    ping_payload,
    replay_payload,
    replay_search_payload,
)

import ballchasing


async def collect(iterator):
    return [item async for item in iterator]


class TestPing:
    async def test_parses_and_stores_identity(self, api, server):
        server.enqueue(
            payload=ping_payload(name="nickm", steam_id="123", patreon_type="gc")
        )

        result = await api.ping()

        assert result.name == "nickm"
        assert api.steam_name == "nickm"
        assert api.steam_id == "123"
        assert api.patreon_type == ballchasing.PatreonType.GC
        assert server.paths() == ["/"]


class TestReplays:
    async def test_get_replay(self, api, server):
        server.enqueue(payload=replay_payload("abc", title="My Replay"))

        replay = await api.get_replay("abc")

        assert replay.id == "abc"
        assert replay.title == "My Replay"
        assert server.paths() == ["/replays/abc"]

    async def test_search_returns_a_page(self, api, server):
        server.enqueue(payload=replay_search_payload(["a", "b"], count=2))

        result = await api.search(count=2)

        assert [r.id for r in result.list] == ["a", "b"]

    async def test_search_omits_unset_filters(self, api, server):
        """pro=None used to be sent as the literal string 'none'."""
        server.enqueue(payload=replay_search_payload([]))

        await api.search()

        query = server.requests[0].query
        assert "pro" not in query
        assert "title" not in query

    async def test_search_sends_pro_when_set(self, api, server):
        server.enqueue(payload=replay_search_payload([]))

        await api.search(pro=True)

        assert server.requests[0].query["pro"] == "true"

    async def test_search_repeats_list_filters(self, api, server):
        server.enqueue(payload=replay_search_payload([]))

        await api.search(player_id=["steam:1", "steam:2"])

        pairs = server.requests[0].query_pairs
        assert ("player-id", "steam:1") in pairs
        assert ("player-id", "steam:2") in pairs

    async def test_get_replays_follows_pagination(self, api, server):
        page2 = f"{server.url}/replays?after=b"
        server.enqueue(payload=replay_search_payload(["a", "b"], next_url=page2))
        server.enqueue(payload=replay_search_payload(["c"]))

        replays = await collect(api.get_replays(count=10))

        assert [r.id for r in replays] == ["a", "b", "c"]
        assert server.call_count == 2

    async def test_get_replays_stops_at_count(self, api, server):
        server.enqueue(payload=replay_search_payload(["a", "b", "c"]))

        replays = await collect(api.get_replays(count=3))

        assert len(replays) == 3
        assert server.call_count == 1

    async def test_get_replays_deep_fetches_each_replay(self, api, server):
        server.enqueue(payload=replay_search_payload(["a", "b"]))
        server.enqueue(payload=replay_payload("a", title="deep-a"))
        server.enqueue(payload=replay_payload("b", title="deep-b"))

        replays = await collect(api.get_replays(count=2, deep=True))

        assert [r.title for r in replays] == ["deep-a", "deep-b"]
        assert server.paths()[1:] == ["/replays/a", "/replays/b"]

    async def test_patch_replay_sends_json(self, api, server):
        server.enqueue(payload={})

        await api.patch_replay("abc", title="new title")

        request = server.requests[0]
        assert request.method == "PATCH"
        assert json.loads(request.body) == {"title": "new title"}

    async def test_delete_replay(self, api, server):
        server.enqueue(payload={})

        await api.delete_replay("abc")

        assert server.requests[0].method == "DELETE"
        assert server.paths() == ["/replays/abc"]


class TestUploads:
    async def test_upload_from_bytes(self, api, server):
        server.enqueue(status=201, payload={"id": "new-id"})

        result = await api.upload_replay_from_bytes("x.replay", b"payload-bytes")

        assert result.id == "new-id"
        request = server.requests[0]
        assert request.method == "POST"
        assert request.path == "/v2/upload"
        assert b"payload-bytes" in request.body

    async def test_upload_sends_visibility_and_group(self, api, server):
        server.enqueue(status=201, payload={"id": "new-id"})

        await api.upload_replay_from_bytes(
            "x.replay",
            b"bytes",
            visibility=ballchasing.Visibility.PRIVATE,
            group="my-group",
        )

        query = server.requests[0].query
        assert query["visibility"] == "private"
        assert query["group"] == "my-group"

    async def test_upload_without_group_omits_it(self, api, server):
        server.enqueue(status=201, payload={"id": "new-id"})

        await api.upload_replay_from_bytes("x.replay", b"bytes")

        assert "group" not in server.requests[0].query

    async def test_upload_from_file(self, tmp_path, api, server):
        replay = tmp_path / "up.replay"
        replay.write_bytes(b"from-disk")
        server.enqueue(status=201, payload={"id": "file-id"})

        result = await api.upload_replay(str(replay))

        assert result.id == "file-id"
        assert b"from-disk" in server.requests[0].body


class TestGroups:
    async def test_get_group(self, api, server):
        server.enqueue(payload=group_payload("g1", name="Finals"))

        group = await api.get_group("g1")

        assert group.id == "g1"
        assert group.name == "Finals"

    async def test_create_group_sends_json(self, api, server):
        server.enqueue(payload={"id": "g-new", "link": "https://example.invalid/g"})

        result = await api.create_group(
            name="Week 1",
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )

        assert result.id == "g-new"
        body = json.loads(server.requests[0].body)
        assert body["name"] == "Week 1"
        assert body["player_identification"] == "by-id"

    async def test_get_groups_follows_pagination(self, api, server):
        page2 = f"{server.url}/groups?after=g2"
        server.enqueue(payload=group_search_payload(["g1", "g2"], next_url=page2))
        server.enqueue(payload=group_search_payload(["g3"]))

        groups = await collect(api.get_groups(count=10))

        assert [g.id for g in groups] == ["g1", "g2", "g3"]

    async def test_patch_group(self, api, server):
        server.enqueue(payload={})

        await api.patch_group("g1", player_identification="by-name")

        assert server.requests[0].method == "PATCH"
        assert json.loads(server.requests[0].body) == {
            "player_identification": "by-name"
        }

    async def test_delete_group(self, api, server):
        server.enqueue(payload={})

        await api.delete_group("g1")

        assert server.requests[0].method == "DELETE"
        assert server.paths() == ["/groups/g1"]

    async def test_get_group_replays_without_recursion(self, api, server):
        server.enqueue(payload=replay_search_payload(["r1", "r2"]))

        replays = await collect(api.get_group_replays("g1"))

        assert [r.id for r in replays] == ["r1", "r2"]

    async def test_get_group_replays_recurses_into_children(self, api, server):
        """Every level must contribute its own replays, not just descend."""
        server.enqueue(payload=group_search_payload(["child"]))  # parent's children
        server.enqueue(payload=group_search_payload([]))  # child's children
        server.enqueue(payload=replay_search_payload(["r-child"]))  # child's replays
        server.enqueue(payload=replay_search_payload(["r-parent"]))  # parent's replays

        replays = await collect(api.get_group_replays("parent", recurse=True))

        assert [r.id for r in replays] == ["r-child", "r-parent"]


class TestDownloads:
    async def test_download_replay_writes_the_file(self, tmp_path, api, server):
        server.enqueue(payload=b"replay-binary")

        await api.download_replay("abc", folder=str(tmp_path))

        written = tmp_path / "abc.replay"
        assert written.read_bytes() == b"replay-binary"
        assert server.paths() == ["/replays/abc/file"]

    async def test_download_replay_content_returns_bytes(self, api, server):
        server.enqueue(payload=b"raw-bytes")

        content = await api.download_replay_content("abc")

        assert content == b"raw-bytes"

    async def test_download_group_walks_children(self, tmp_path, api, server):
        server.enqueue(payload=group_search_payload([]))  # no child groups
        server.enqueue(payload=replay_search_payload(["r1"]))  # one replay
        server.enqueue(payload=b"replay-binary")  # its file

        groups, replays = await api.download_group("g1", folder=str(tmp_path))

        assert (groups, replays) == (0, 1)
        assert (tmp_path / "g1" / "r1.replay").read_bytes() == b"replay-binary"


class TestMaps:
    async def test_get_maps(self, api, server):
        server.enqueue(payload={"stadium_p": "DFH Stadium"})

        maps = await api.get_maps()

        assert maps == {"stadium_p": "DFH Stadium"}


class TestDateHandling:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    async def test_dates_are_sent_as_rfc3339(self, api, server, value, expected):
        server.enqueue(payload=replay_search_payload([]))

        await api.search(created_after=value)

        assert server.requests[0].query["created-after"] == expected

    async def test_naive_datetimes_are_treated_as_utc(self, api, server):
        server.enqueue(payload=replay_search_payload([]))

        naive = datetime(2024, 1, 2, 3, 4, 5)  # noqa: DTZ001 -- naive is the point
        await api.search(created_after=naive)

        assert server.requests[0].query["created-after"] == "2024-01-02T03:04:05Z"
