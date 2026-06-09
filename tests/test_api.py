import pytest
import asyncio
import datetime as dt
import random
import ballchasing
from ballchasing.enums import Visibility

TEST_REPLAY_ID = "f1fa6c0e-3d6f-4475-b844-5f6d7099aebe"
TEST_REPLAY_PATH = "tests/replays/uploadme.replay"
TEST_REPLAY_PATH2 = "tests/replays/uploadme2.replay"
TEST_GROUP = "test_group-yq5fr2lfsj"
TEST_GROUP_REPLAY = "6d8df3f0-d305-434d-9aaf-e6dfb0fce358"
TEST_GROUP_REPLAY2 = "868e7fa7-f458-499a-9af7-2a9b124d56ec"
TEST_GROUP_UPLOAD = "test_api_upload-k3047kv72j"
TEST_GROUP_PATCH = "test_group_patch-hkgp40xdq9"
UPLOADER_ID = "76561197960409023"

SORT_BY = "replay-date"
SORT_DIR = "desc"


async def gather(result):
    # Gather async iterator into list and return
    final = []
    async for r in result:
        final.append(r)
    return final


def to_dt(val: str):
    # Converts string to UTC datetime object
    return dt.datetime.strptime(val, "%Y-%m-%dT%H:%M:%S.%f")


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    def raise_for_status(self):
        raise AssertionError(f"Unexpected raise_for_status for status {self.status}")


@pytest.fixture()
async def local_api(monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr("ballchasing.api.asyncio.sleep", instant_sleep)

    api = ballchasing.Api(auth_key="test-key", sleep_time_on_rate_limit=0.1)
    try:
        yield api
    finally:
        await api.close()


class TestApi:
    @pytest.mark.asyncio
    async def test_ping(self, bapi):
        result = await bapi.ping()
        assert result is not None and isinstance(result, dict)
        assert bapi.steam_name == result["name"]
        assert bapi.steam_id == result["steam_id"]
        assert bapi.patron_type == result["type"]

    @pytest.mark.asyncio
    async def test_get_replay(self, bapi):
        result = await bapi.get_replay(TEST_REPLAY_ID)
        assert result["id"] == TEST_REPLAY_ID
        assert result["team_size"] == 2
        assert result["uploader"]["name"] == "nickm"

    @pytest.mark.asyncio
    async def test_get_replays(self, bapi):
        after = to_dt("2022-11-28T00:00:00.00")
        before = to_dt("2022-11-29T00:00:00.00")
        result = bapi.get_replays(
            uploader="76561197960409023",
            replay_before=before,
            replay_after=after,
            season="f8",
            playlist="ranked-doubles",
            sort_by="replay-date",
            sort_dir="desc",
        )
        replays = await gather(result)

        assert len(replays) == 3
        assert replays[0]["id"] == "183f7b59-6816-4e7f-bf96-5521290a5b5e"
        assert replays[1]["id"] == "9f060caf-c907-4c3c-81c3-6df0604aaf0a"
        assert replays[2]["id"] == "3a5c54c3-c0df-4b5e-9957-eae93fefc48f"

    @pytest.mark.asyncio
    async def test_patch_replay(self, bapi):
        # Patching will only succeed if you own the replay
        new_title = f"ApiTest{random.randint(1000, 9999)}"
        await bapi.patch_replay(TEST_REPLAY_ID, title=new_title)

        result = await bapi.get_replay(TEST_REPLAY_ID)
        assert result["title"] == new_title

    @pytest.mark.asyncio
    async def test_upload_delete_replay(self, bapi):
        result = await bapi.upload_replay(
            "tests/replays/uploadme.replay",
            visibility=Visibility.PRIVATE,
            group=TEST_GROUP_UPLOAD,
        )

        assert result["id"] is not None
        assert result["location"] is not None

        # Clean up so we don't have a conflict next time
        await bapi.delete_replay(result["id"])

    @pytest.mark.asyncio
    async def test_get_group(self, bapi):
        result = await bapi.get_group(TEST_GROUP)

        assert result["id"] == TEST_GROUP
        assert result["name"] == "test_group"

    @pytest.mark.asyncio
    async def test_get_groups(self, bapi):
        after = to_dt("2023-01-04T00:00:00.00")
        before = to_dt("2023-01-05T00:00:00.00")

        result = bapi.get_groups(
            creator=UPLOADER_ID,
            created_before=before,
            created_after=after,
            sort_by="created",
            sort_dir="desc",
        )
        groups = await gather(result)

        assert groups[0]["id"] == "test_api_upload-k3047kv72j"
        assert groups[0]["name"] == "test_api_upload"
        assert groups[1]["id"] == "test_group-yq5fr2lfsj"
        assert groups[1]["name"] == "test_group"

    @pytest.mark.asyncio
    async def test_create_delete_group(self, bapi):
        group_title = f"temp_group_{random.randint(1000, 9999)}"
        result = await bapi.create_group(
            name=group_title,
            player_identification="by-id",
            team_identification="by-player-clusters",
        )

        assert result["id"] is not None
        assert result["link"] is not None

        await bapi.delete_group(result["id"])

    @pytest.mark.asyncio
    async def test_patch_group(self, bapi):
        await bapi.patch_group(
            TEST_GROUP_PATCH,
            player_identification="by-name",
            team_identification="by-distinct-players",
        )
        result = await bapi.get_group(TEST_GROUP_PATCH)
        assert result["player_identification"] == "by-name"
        assert result["team_identification"] == "by-distinct-players"

        await bapi.patch_group(
            TEST_GROUP_PATCH,
            player_identification="by-id",
            team_identification="by-player-clusters",
        )
        result = await bapi.get_group(TEST_GROUP_PATCH)
        assert result["player_identification"] == "by-id"
        assert result["team_identification"] == "by-player-clusters"

    @pytest.mark.asyncio
    async def test_download_replay(self, tmp_path, bapi):
        replay = tmp_path / f"{TEST_REPLAY_ID}.replay"
        await bapi.download_replay(TEST_REPLAY_ID, folder=tmp_path)
        assert replay.is_file()

    @pytest.mark.asyncio
    async def test_download_group(self, tmp_path, bapi):
        replay1 = tmp_path / TEST_GROUP / f"{TEST_GROUP_REPLAY}.replay"
        replay2 = tmp_path / TEST_GROUP / f"{TEST_GROUP_REPLAY2}.replay"
        await bapi.download_group(TEST_GROUP, folder=tmp_path)
        assert replay1.is_file()
        assert replay2.is_file()

    @pytest.mark.asyncio
    async def test_get_maps(self, bapi):
        result = await bapi.get_maps()
        assert len(result) >= 56  # Current number of maps (1/4/23)
        assert "Neo Tokyo" in result.values()
        assert "DFH Stadium" in result.values()


class TestRetrySafeUploads:
    @pytest.mark.asyncio
    async def test_upload_replay_from_bytes_retries_with_fresh_form_data(
        self, local_api
    ):
        attempts = []

        async def fake_post(url, **kwargs):
            form_data = kwargs["data"]
            attempts.append(form_data)
            form_data()

            if len(attempts) == 1:
                raise ConnectionError("boom")

            return FakeResponse(
                201,
                {"id": "retry-id", "link": "https://ballchasing.com/replay/retry-id"},
            )

        local_api._session.post = fake_post

        result = await local_api.upload_replay_from_bytes(
            "retry.replay",
            b"replay-bytes",
            visibility=Visibility.PRIVATE,
        )

        assert result.id == "retry-id"
        assert len(attempts) == 2
        assert attempts[0] is not attempts[1]

    @pytest.mark.asyncio
    async def test_upload_replay_retries_with_fresh_form_data_after_429(
        self, tmp_path, local_api
    ):
        replay_path = tmp_path / "retry-upload.replay"
        replay_path.write_bytes(b"replay-bytes")

        attempts = []
        file_handles = []

        async def fake_post(url, **kwargs):
            form_data = kwargs["data"]
            attempts.append(form_data)
            file_handles.append(form_data._fields[0][2])
            form_data()

            if len(attempts) == 1:
                return FakeResponse(429)

            return FakeResponse(
                201,
                {"id": "upload-id", "link": "https://ballchasing.com/replay/upload-id"},
            )

        local_api._session.post = fake_post

        result = await local_api.upload_replay(
            str(replay_path),
            visibility=Visibility.PRIVATE,
        )

        assert result.id == "upload-id"
        assert len(attempts) == 2
        assert attempts[0] is not attempts[1]
        assert file_handles[0] is not file_handles[1]
        assert all(handle.closed for handle in file_handles)

    @pytest.mark.skip(
        reason="Had trouble testing this. Works in console but not in pytest. Disabling due to lack of importance"
    )
    @pytest.mark.asyncio
    async def test_generate_tsvs(self, tmp_path, bapi):
        result = await bapi.generate_tsvs(
            replays=[TEST_REPLAY_ID],
            path_name=str(tmp_path),
            player_suffix="player",
            team_suffix="team",
            replay_suffix="replay",
        )
        player_file = tmp_path / "player"
        team_file = tmp_path / "team"
        replay_file = tmp_path / "replay"

        files = [e for e in tmp_path.iterdir()]
        print(f"Files: {files}")

        assert len(list(tmp_path.iterdir())) > 0
        assert player_file.is_file()
        assert team_file.is_file()
        assert replay_file.is_file()
        assert player_file.stat().st_size > 0
        assert team_file.stat().st_size > 0
        assert replay_file.stat().st_size > 0
