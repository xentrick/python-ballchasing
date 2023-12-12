import os
import time
import logging
from datetime import datetime
from typing import Optional, Iterator, Union, List, Callable, AsyncIterator, Type
from types import TracebackType

from aiohttp import ClientSession, TCPConnector, ClientResponse, FormData
import asyncio
import aiofiles

from ballchasing import models
from ballchasing.enums import (
    Rank,
    Playlist,
    GroupSortBy,
    SortDir,
    ReplaySortBy,
    PlayerIdentificationBy,
    TeamIdentificationBy,
    MatchResult,
    Visibility,
    PatreonType,
)
from ballchasing import util

log = logging.getLogger("ballchasing")

DEFAULT_URL = "https://ballchasing.com/api"


class Api:
    """
    Class for communication with ballchasing.com API (https://ballchasing.com/doc/api)
    """

    def __init__(
        self,
        auth_key: str,
        sleep_time_on_rate_limit: float | None = None,
        print_on_rate_limit: bool = False,
        base_url: str | None = None,
        max_connections: int = 0,
        patreon_type: PatreonType = PatreonType.REGULAR,
    ):
        """

        :param auth_key: authentication key for API calls.
        :param sleep_time_on_rate_limit: seconds to wait after being rate limited.
                                         Default value is calculated depending on patron type.
        :param print_on_rate_limit: whether or not to print upon rate limits.
        :param base_url: Ballchasing URL string
        :param max_connections: Max concurrent requests at once (Default: 0)
        """

        self.auth_key = auth_key
        self.headers = {"Authorization": self.auth_key}
        self.max_connections = max_connections
        self.connector = TCPConnector(limit=self.max_connections)

        self.steam_name: str | None = None
        self.steam_id: str | None = None
        self.patreon_type: PatreonType = patreon_type
        self.rate_limit_count = 0
        self.base_url = DEFAULT_URL if base_url is None else base_url

        if sleep_time_on_rate_limit is None:
            self.sleep_time_on_rate_limit = self.patreon_type.rate_limit()
        else:
            self.sleep_time_on_rate_limit = sleep_time_on_rate_limit
        self.print_on_rate_limit = print_on_rate_limit

    async def _request(
        self, url_or_endpoint: str, method: str, **params
    ) -> "ClientResponse":
        """
        Helper method for all requests.

        :param url: url or endpoint for request.
        :param method: the method to use.
        :param params: parameters for GET request.
        :return: the request result.
        """
        url = (
            f"{self.base_url}{url_or_endpoint}"
            if url_or_endpoint.startswith("/")
            else url_or_endpoint
        )
        retries = 0
        while True:
            try:
                connector = TCPConnector(limit=self.max_connections)
                async with ClientSession(
                    connector=connector, headers=self.headers
                ) as session:
                    match method:
                        case "GET":
                            r = await session.get(url, **params)
                        case "POST":
                            r = await session.post(url, **params)
                        case "PUT":
                            r = await session.put(url, **params)
                        case "PATCH":
                            r = await session.patch(url, **params)
                        case "DELETE":
                            r = await session.delete(url, **params)
                        case _:
                            raise ValueError("Invalid HTTP method.")
                    retries = 0
            except ConnectionError as e:
                log.error("Connection error, trying again in 10 seconds...")
                await asyncio.sleep(10)
                retries += 1
                if retries >= 10:
                    raise e
                continue
            except TimeoutError as e:
                log.error("Connection to ballchasing timed out.")
                raise e

            if 200 <= r.status < 300:
                return r
            elif r.status == 429:
                if self.print_on_rate_limit:
                    log.warning(f"429 {url} {self.rate_limit_count}")
                if self.sleep_time_on_rate_limit:
                    await asyncio.sleep(self.sleep_time_on_rate_limit)
                self.rate_limit_count += 1
            else:
                raise ValueError(r)

    async def ping(self) -> models.Ping:
        """
        Use this API to:

        - check if your API key is correct
        - check if ballchasing API is reachable

        This method runs automatically at initialization and the steam name and id as well as patron type are stored.
        :return: ping response.
        """
        resp = await self._request("/", "GET")
        result = await resp.json()
        ping = models.Ping(**result)

        self.steam_name = ping.name
        self.steam_id = ping.steam_id
        self.patreon_type = ping.type

        self.sleep_time_on_rate_limit = self.patreon_type.rate_limit()
        return ping

    async def search(
        self,
        player_name: list[str] = [],
        player_id: list[str] = [],
        title: str | None = None,
        playlist: list[Playlist] = [],
        season: list[str] = [],
        match_result: MatchResult | None = None,
        min_rank: Rank | None = None,
        max_rank: Rank | None = None,
        pro: bool | None = None,
        uploader: str | None = None,
        group_id: str | None = None,
        map_id: str | None = None,
        created_before: str | datetime | None = None,
        created_after: str | datetime | None = None,
        replay_after: str | datetime | None = None,
        replay_before: str | datetime | None = None,
        count: int = 150,
        sort_by: ReplaySortBy | None = None,
        sort_dir: SortDir = SortDir.DESCENDING,
    ) -> models.ReplaySearch:
        """
        This endpoint lets you filter and retrieve replays.

        :param title: filter replays by title.
        :param player_name: filter replays by a player’s name.
        :param player_id: filter replays by a player’s platform id in the $platform:$id, e.g. steam:76561198141161044,
        ps4:gamertag, … You can filter replays by multiple player ids, e.g ?player-id=steam:1&player-id=steam:2
        :param playlist: filter replays by one or more playlists.
        :param season: filter replays by season. Must be a number between 1 and 14 (for old seasons)
                       or f1, f2, … for the new free to play seasons
        :param match_result: filter your replays by result.
        :param min_rank: filter your replays based on players minimum rank.
        :param max_rank: filter your replays based on players maximum rank.
        :param pro: only include replays containing at least one pro player.
        :param uploader: only include replays uploaded by the specified user. Accepts either the
                         numerical 76*************44 steam id, or the special value 'me'
        :param group_id: only include replays belonging to the specified group. This only include replays immediately
                         under the specified group, but not replays in child groups
        :param map_id: only include replays in the specified map. Check get_maps for the list of valid map codes
        :param created_before: only include replays created (uploaded) before some date.
                               RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param created_after: only include replays created (uploaded) after some date.
                              RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param replay_after: only include replays for games that happened after some date.
                             RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param replay_before: only include replays for games that happened before some date.
                              RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param count: returns at most count replays. Since the implementation uses an iterator it supports iterating
                      past the limit of 200 set by the API
        :param sort_by: sort replays according the selected field
        :param sort_dir: sort direction
        :param deep: whether or not to get full stats for each replay (will be much slower).
        :return: an iterator over the replays returned by the API.
        """
        url = f"{self.base_url}/replays"
        params = {
            "title": title,
            "player-name": player_name,
            "player-id": player_id,
            "playlist": playlist,
            "season": season,
            "match-result": match_result,
            "min-rank": min_rank,
            "max-rank": max_rank,
            "pro": str(pro).lower(),
            "uploader": uploader,
            "group": group_id,
            "map": map_id,
            "created-before": util.rfc3339(created_before),
            "created-after": util.rfc3339(created_after),
            "replay-date-after": util.rfc3339(replay_after),
            "replay-date-before": util.rfc3339(replay_before),
            "sort-by": sort_by,
            "sort-dir": sort_dir,
            "count": count,
        }
        # Remove all NoneType parameters.
        params = dict((k, v) for k, v in params.items() if v is not None)
        resp = await self._request(url, "GET", params=params)
        data = await resp.json()
        return models.ReplaySearch(**data)

    async def get_replays(
        self,
        player_name: list[str] = [],
        player_id: list[str] = [],
        title: str | None = None,
        playlist: list[Playlist] = [],
        season: list[str] = [],
        match_result: MatchResult | None = None,
        min_rank: Rank | None = None,
        max_rank: Rank | None = None,
        pro: bool | None = None,
        uploader: str | None = None,
        group_id: str | None = None,
        map_id: str | None = None,
        created_before: str | datetime | None = None,
        created_after: str | datetime | None = None,
        replay_after: str | datetime | None = None,
        replay_before: str | datetime | None = None,
        count: int = 150,
        sort_by: ReplaySortBy | None = None,
        sort_dir: SortDir = SortDir.DESCENDING,
        deep: bool = False,
    ) -> AsyncIterator[models.Replay]:
        """
        This endpoint lets you filter and retrieve replays. The implementation returns an iterator.

        :param title: filter replays by title.
        :param player_name: filter replays by a player’s name.
        :param player_id: filter replays by a player’s platform id in the $platform:$id, e.g. steam:76561198141161044,
        ps4:gamertag, … You can filter replays by multiple player ids, e.g ?player-id=steam:1&player-id=steam:2
        :param playlist: filter replays by one or more playlists.
        :param season: filter replays by season. Must be a number between 1 and 14 (for old seasons)
                       or f1, f2, … for the new free to play seasons
        :param match_result: filter your replays by result.
        :param min_rank: filter your replays based on players minimum rank.
        :param max_rank: filter your replays based on players maximum rank.
        :param pro: only include replays containing at least one pro player.
        :param uploader: only include replays uploaded by the specified user. Accepts either the
                         numerical 76*************44 steam id, or the special value 'me'
        :param group_id: only include replays belonging to the specified group. This only include replays immediately
                         under the specified group, but not replays in child groups
        :param map_id: only include replays in the specified map. Check get_maps for the list of valid map codes
        :param created_before: only include replays created (uploaded) before some date.
                               RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param created_after: only include replays created (uploaded) after some date.
                              RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param replay_after: only include replays for games that happened after some date.
                             RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param replay_before: only include replays for games that happened before some date.
                              RFC3339 format, e.g. '2020-01-02T15:00:05+01:00'
        :param count: returns at most count replays. Since the implementation uses an iterator it supports iterating
                      past the limit of 200 set by the API
        :param sort_by: sort replays according the selected field
        :param sort_dir: sort direction
        :param deep: whether or not to get full stats for each replay (will be much slower).
        :return: an iterator over the replays returned by the API.
        """
        url = f"{self.base_url}/replays"
        params = {
            "title": title,
            "player-name": player_name,
            "player-id": player_id,
            "playlist": playlist,
            "season": season,
            "match-result": match_result,
            "min-rank": min_rank,
            "max-rank": max_rank,
            "pro": pro,
            "uploader": uploader,
            "group": group_id,
            "map": map_id,
            "created-before": util.rfc3339(created_before),
            "created-after": util.rfc3339(created_after),
            "replay-date-after": util.rfc3339(replay_after),
            "replay-date-before": util.rfc3339(replay_before),
            "sort-by": sort_by,
            "sort-dir": sort_dir,
        }
        # Remove all NoneType parameters.
        params = dict((k, v) for k, v in params.items() if v is not None)

        left = count
        while left > 0:
            request_count = min(left, 200)
            params["count"] = request_count
            resp = await self._request(url, "GET", params=params)
            data = await resp.json()

            replays = models.ReplaySearch(**data)
            if not deep:
                # yield from batch
                # async for r in batch:
                for r in replays.list:
                    yield r
            else:
                # yield from (self.get_replay(r["id"]) for r in batch)
                # async for r in batch:
                for r in replays.list:
                    replay = await self.get_replay(r.id)
                    yield replay

            if not replays.next:
                break

            url = replays.next
            left -= len(replays.list)
            params = {}

    async def get_replay(self, replay_id: str) -> models.Replay:
        """
        Retrieve a given replay’s details and stats.

        :param replay_id: the replay id.
        :return: the result of the GET request.
        """
        r = await self._request(f"/replays/{replay_id}", "GET")
        data = await r.json()
        return models.Replay(**data)

    async def patch_replay(self, replay_id: str, **params) -> None:
        """
        This endpoint can patch one or more fields of the specified replay

        :param replay_id: the replay id.
        :param params: parameters for the PATCH request.
        """
        await self._request(f"/replays/{replay_id}", "PATCH", json=params)

    async def upload_replay(
        self,
        replay_file: str,
        visibility: Visibility = Visibility.PUBLIC,
        group: str | None = None,
    ) -> dict:
        """
        Use this API to upload a replay file to ballchasing.com.

        :param replay_file: replay file to upload.
        :param visibility: to set the visibility of the uploaded replay. (Default: Public)
        :param group: assign replay to a specific group id
        :return: the result of the POST request.
        """
        with open(replay_file, "rb") as fd:
            files = FormData()
            files.add_field(
                "file",
                open(replay_file, "rb"),
                filename=replay_file,
            )

            r = await self._request(
                f"/v2/upload",
                "POST",
                data=files,
                params={"visibility": visibility, "group": group},
            )
        return await r.json()

    async def upload_replay_from_bytes(
        self,
        name: str,
        replay_data: bytes,
        visibility: Visibility = Visibility.PUBLIC,
        group: str | None = None,
    ) -> dict:
        """
        Use this API to upload a replay file to ballchasing.com.

        :param name: Desired name of file (Can be anything).
        :param replay_data: bytes like object to be uploaded.
        :param visibility: to set the visibility of the uploaded replay. (Default: Public)
        :param group: assign replay to a specific group id
        :return: the result of the POST request.
        """
        files = FormData()
        files.add_field(
            "file",
            replay_data,
            filename=name,
        )

        r = await self._request(
            f"/v2/upload",
            "POST",
            data=files,
            params={"visibility": visibility, "group": group},
        )

        return await r.json()

    async def delete_replay(self, replay_id: str) -> None:
        """
        This endpoint deletes the specified replay.
        WARNING: This operation is permanent and undoable.

        :param replay_id: the replay id.
        """
        await self._request(f"/replays/{replay_id}", "DELETE")

    async def get_groups(
        self,
        name: str | None = None,
        creator: str | None = None,
        group: str | None = None,
        created_before: str | datetime | None = None,
        created_after: str | datetime | None = None,
        count: int = 200,
        sort_by: GroupSortBy = GroupSortBy.CREATED,
        sort_dir: SortDir = SortDir.DESCENDING,
    ) -> AsyncIterator[models.ReplayGroup]:
        """
        This endpoint lets you filter and retrieve replay groups.

        :param name: filter groups by name
        :param creator: only include groups created by the specified user.
                        Accepts either the numerical 76*************44 steam id, or the special value me
        :param group: only include children of the specified group
        :param created_before: only include groups created (uploaded) before some date.
                               RFC3339 format, e.g. 2020-01-02T15:00:05+01:00
        :param created_after: only include groups created (uploaded) after some date.
                              RFC3339 format, e.g. 2020-01-02T15:00:05+01:00
        :param count: returns at most count groups. Since the implementation uses an iterator it supports iterating
                      past the limit of 200 set by the API
        :param sort_by: Sort groups according the selected field.
        :param sort_dir: Sort direction.
        :return: an iterator over the groups returned by the API.
        """
        url = f"{self.base_url}/groups/"
        params = {
            "name": name,
            "creator": creator,
            "group": group,
            "created-before": util.rfc3339(created_before),
            "created-after": util.rfc3339(created_after),
            "sort-by": sort_by,
            "sort-dir": sort_dir,
        }
        params = dict((k, v) for k, v in params.items() if v is not None)

        left = count
        while left > 0:
            request_count = min(left, 200)
            params["count"] = request_count
            resp = await self._request(url, "GET", params=params)
            data = await resp.json()
            groups = models.GroupSearch(**data)

            # yield from batch
            for g in groups.list:
                yield g

            if not groups.next:
                break

            url = groups.next
            left -= len(groups.list)
            params = {}

    async def create_group(
        self,
        name: str,
        player_identification: PlayerIdentificationBy,
        team_identification: TeamIdentificationBy,
        parent: str | None = None,
    ) -> dict:
        """
        Use this API to create a new replay group.

        :param name: the new group name.
        :param player_identification: how to identify the same player across multiple replays.
                                      Some tournaments (e.g. RLCS) make players use a pool of generic Steam accounts,
                                      meaning the same player could end up using 2 different accounts in 2 series.
                                      That's when the `by-name` comes in handy
        :param team_identification: How to identify the same team across multiple replays.
                                    Set to `by-distinct-players` if teams have a fixed roster of players for
                                    every single game. In some tournaments/leagues, teams allow player rotations,
                                    or a sub can replace another player, in which case use `by-player-clusters`.
        :param parent: if set,the new group will be created as a child of the specified group
        :return: the result of the POST request.
        """
        json = {
            "name": name,
            "player_identification": player_identification,
            "team_identification": team_identification,
            "parent": parent,
        }
        r = await self._request(f"/groups", "POST", json=json)
        return await r.json()

    async def get_group(self, group_id: str) -> models.ReplayGroup:
        """
        This endpoint retrieves a specific replay group info and stats given its id.

        :param group_id: the group id.
        :return: the group info with stats.
        """
        r = await self._request(f"/groups/{group_id}", "GET")
        data = await r.json()
        return models.ReplayGroup(**data)

    async def patch_group(self, group_id: str, **params) -> None:
        """
        This endpoint can patch one or more fields of the specified group.

        :param group_id: the group id
        :param params: parameters for the PATCH request.
        """
        await self._request(f"/groups/{group_id}", "PATCH", json=params)

    async def delete_group(self, group_id: str) -> None:
        """
        This endpoint deletes the specified group.
        WARNING: This operation is permanent and undoable.

        :param group_id: the group id.
        """
        await self._request(f"/groups/{group_id}", "DELETE")

    async def get_group_replays(
        self, group_id: str, deep: bool = False
    ) -> AsyncIterator[models.Replay]:
        """
        Finds all replays in a group, including child groups.

        :param group_id: the base group id.
        :param deep: whether or not to get full stats for each replay (will be much slower).
        :return: an iterator over all the replays in the group.
        """
        # child_groups = await self.get_groups(group=group_id)
        async for child in self.get_groups(group=group_id):
            async for replay in self.get_group_replays(child.id, deep):
                yield replay
        async for replay in self.get_replays(group_id=group_id, deep=deep):
            yield replay

    async def download_replay(self, replay_id: str, folder: str) -> None:
        """
        Download a replay file.

        :param replay_id: the replay id.
        :param folder: the folder to download into.
        """
        r = await self._request(f"/replays/{replay_id}/file", "GET")
        async with aiofiles.open(f"{folder}/{replay_id}.replay", mode="wb") as fd:
            await fd.write(await r.read())

    async def download_replay_content(self, replay_id: str) -> bytes:
        """
        Download a replay file contents

        :param replay_id: the replay id.
        """
        r = await self._request(f"/replays/{replay_id}/file", "GET")
        return await r.read()

    async def download_group(self, group_id: str, folder: str, recursive=True):
        """
        Download an entire group.

        :param group_id: the base group id.
        :param folder: the folder in which to create the group folder.
        :param recursive: whether or not to create new folders for child groups.
        """
        folder = os.path.join(folder, group_id)
        if recursive:
            os.makedirs(folder, exist_ok=True)
            async for child_group in self.get_groups(group=group_id):
                await self.download_group(child_group.id, folder, True)
            async for replay in self.get_replays(group_id=group_id):
                await self.download_replay(replay.id, folder)
        else:
            async for replay in self.get_group_replays(group_id):
                await self.download_replay(replay.id, folder)

    async def get_maps(self):
        """
        Use this API to get the list of map codes to map names (map as in stadium).
        """
        res = await self._request("/maps", "GET")
        return await res.json()

    def __str__(self):
        return (
            f"BallchasingApi[key={self.auth_key},name={self.steam_name},"
            f"steam_id={self.steam_id},type={self.patreon_type}]"
        )


# if __name__ == "__main__":
#     # Basic initial tests
#     import sys

#     token = sys.argv[1]
#     api = Api(token)
#     print(api)
#     # api.get_replays(season="123")
#     # api.delete_replay("a22a8c81-fadd-4453-914e-ae54c2b8391f")
#     upload_response = api.upload_replay(
#         open("4E2B22344F748C6EB4922DB8CC8AC282.replay", "rb")
#     )
#     replays_response = api.get_replays()
#     replay_response = api.get_replay(next(replays_response)["id"])

#     groups_response = api.get_groups()
#     group_response = api.get_group(next(groups_response)["id"])

#     create_group_response = api.create_group(
#         f"test-{time.time()}", "by-id", "by-distinct-players"
#     )
#     api.patch_group(
#         create_group_response["id"], team_identification="by-player-clusters"
#     )

#     api.patch_replay(upload_response["id"], group=create_group_response["id"])

#     api.delete_group(create_group_response["id"])
#     api.delete_replay(upload_response["id"])
#     print("Nice")
