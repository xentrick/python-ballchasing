import pytest
import asyncio
import datetime as dt
import random
from ballchasing.constants import Season, Visibility

TEST_REPLAY_ID = "f1fa6c0e-3d6f-4475-b844-5f6d7099aebe"
TEST_REPLAY_PATH = "tests/replays/uploadme.replay"
TEST_REPLAY_PATH2 = "tests/replays/uploadme2.replay"
UPLOADER_ID = "76561197960409023"

SORT_BY = "replay-date"
SORT_DIR = "desc"

async def gather(result):
    # Gather async iterator into list and return
    final = []
    async for r in result: final.append(r)
    return final

def to_dt(val: str):
    # Converts string to UTC datetime object
    return dt.datetime.strptime(val, '%Y-%m-%dT%H:%M:%S.%f')

class TestApi:

    @pytest.mark.asyncio
    async def test_ping(self, bapi):
        result = await bapi.ping()
        print(f"APIKEY: {bapi.auth_key}")
        assert result is not None and isinstance(result, dict)
        assert bapi.steam_name == result['name']
        assert bapi.steam_id == result['steam_id']
        assert bapi.patron_type == result['type']

    @pytest.mark.asyncio
    async def test_get_replay(self, bapi):
        result = await bapi.get_replay(TEST_REPLAY_ID)
        assert result['id'] == TEST_REPLAY_ID
        assert result['team_size'] == 2
        assert result['uploader']['name'] == "nickm"

    @pytest.mark.asyncio
    async def test_get_replays(self, bapi):
        after = to_dt('2022-11-28T00:00:00.00')
        before = to_dt('2022-11-29T00:00:00.00')
        result = bapi.get_replays(uploader="76561197960409023", replay_before=before, replay_after=after, season="f8", playlist="ranked-doubles", sort_by="replay-date", sort_dir="desc")
        replays = await gather(result)

        assert len(replays) == 3
        assert replays[0]['id'] == '183f7b59-6816-4e7f-bf96-5521290a5b5e'
        assert replays[1]['id'] == '9f060caf-c907-4c3c-81c3-6df0604aaf0a'
        assert replays[2]['id'] == '3a5c54c3-c0df-4b5e-9957-eae93fefc48f'

    @pytest.mark.asyncio
    async def test_patch_replay(self, bapi):
        # Patching will only succeed if you own the replay
        new_title = f"ApiTest{random.randint(1000,9999)}"
        await bapi.patch_replay(TEST_REPLAY_ID, title=new_title)

        result = await bapi.get_replay(TEST_REPLAY_ID)
        assert result['title'] == new_title

    @pytest.mark.asyncio
    async def test_upload_replay(self, bapi):
        result = await bapi.upload_replay("tests/replays/uploadme.replay", visibility=Visibility.PRIVATE)

        assert result['id'] is not None
        assert result['location'] is not None

        # Clean up so we don't have a conflict next time
        await bapi.delete_replay(result['id'])


