import asyncio
import logging
import os
import random
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import aiofiles
from aiohttp import ClientResponse, ClientSession, ClientTimeout, FormData, TCPConnector
from aiolimiter import AsyncLimiter

from ballchasing import models, util
from ballchasing.enums import (
    GroupSortBy,
    MatchResult,
    PatreonType,
    PlayerIdentificationBy,
    Playlist,
    Rank,
    ReplaySortBy,
    SortDir,
    TeamIdentificationBy,
    Visibility,
)
from ballchasing.exceptions import (
    BackoffLimitExceeded,
    BallchasingFault,
    DuplicateReplay,
    MissingAPIKey,
    UserFault,
)

log = logging.getLogger("ballchasing")

DEFAULT_URL = "https://ballchasing.com/api"
DEFAULT_TIMEOUT = 30
RETRY_COUNT = 5
# Caps concurrent sockets only. This is deliberately well above any tier's
# requests-per-second: a pool smaller than rps * latency becomes the real
# throttle and holds throughput below the configured rate.
DEFAULT_MAX_CONNECTION = 100
MAX_BACKOFF_ATTEMPTS = 15
BACKOFF_MULTIPLIER = 3
# Fraction of ballchasing's documented ceiling we actually aim for, leaving
# room for network jitter and clock skew between us and their window.
DEFAULT_RATE_LIMIT_SAFETY = 0.9
MIN_REQUESTS_PER_SECOND = 0.1
RequestDataFactory = Callable[[], tuple[Any, Callable[[], None] | None]]


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
        max_connections: int = DEFAULT_MAX_CONNECTION,
        patreon_type: PatreonType = PatreonType.REGULAR,
        timeout=DEFAULT_TIMEOUT,
        rate_limit_safety: float = DEFAULT_RATE_LIMIT_SAFETY,
        limiter: AsyncLimiter | None = None,
    ):
        """

        :param auth_key: authentication key for API calls.
        :param sleep_time_on_rate_limit: base seconds to wait after being rate
                                         limited. Defaults to one request
                                         period for the patreon tier.
        :param print_on_rate_limit: whether or not to print upon rate limits.
        :param base_url: Ballchasing URL string
        :param max_connections: max concurrent TCP connections. This is a
                                connection-pool bound, not a rate: keep it
                                comfortably above requests_per_second times
                                your typical latency or it, rather than the
                                limiter, becomes the throttle.
        :param patreon_type: tier used to derive the request rate until
                             :meth:`ping` reports the real one.
        :param rate_limit_safety: fraction of the documented ceiling to target.
        :param limiter: share one limiter across several Api instances that use
                        the same auth key. Ballchasing rate limits per account,
                        so separate instances with separate limiters multiply
                        the effective rate. When given, it is used as-is and
                        never rebuilt.
        """

        self.auth_key = auth_key
        self.headers = {"Authorization": self.auth_key}
        self.max_connections = max_connections
        self.patreon_type: PatreonType = patreon_type
        self.timeout_value = timeout
        self.rate_limit_safety = rate_limit_safety

        self.steam_name: str | None = None
        self.steam_id: str | None = None
        self.rate_limit_count = 0
        self.base_url = DEFAULT_URL if base_url is None else base_url
        self.total_requests = 0

        # Remembered so ping() can refresh the derived default when it learns
        # the real tier, without overwriting a caller's explicit choice.
        self._sleep_time_override = sleep_time_on_rate_limit
        self.sleep_time_on_rate_limit = (
            sleep_time_on_rate_limit
            if sleep_time_on_rate_limit is not None
            else 1 / self.requests_per_second
        )

        self._external_limiter = limiter

        # The aiohttp session is created lazily on the first request, because
        # TCPConnector requires a running event loop. This keeps Api() itself
        # constructible from synchronous code.
        self.timeout = ClientTimeout(total=self.timeout_value)
        self.connector: TCPConnector | None = None
        self._session: ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None

        # AIO Limiter
        self.configure_limiter()

        self.print_on_rate_limit = print_on_rate_limit

    @classmethod
    async def create(cls, **kwargs):
        instance = cls(**kwargs)
        await instance.ping()
        await instance.reconfigure_session()
        return instance

    async def reconfigure_session(self):
        """Discard the current session and re-tune the limiter.

        The next request rebuilds the session with the new settings.
        """
        await self.close()
        self.configure_limiter()

    async def _ensure_session(self) -> ClientSession:
        """Return the aiohttp session, creating it on the running loop if needed."""
        loop = asyncio.get_running_loop()
        session = self._session

        if session is not None and self._session_loop is not loop:
            # An Api built on one loop is being used on another. We cannot await
            # a close on a loop that is likely already dead, so drop the old
            # session and warn that it was abandoned.
            log.warning(
                "Api session was created on a different event loop; rebuilding. "
                "The previous session was abandoned without being closed."
            )
            session = self._session = None
            self.connector = None

        if session is None or session.closed:
            log.debug(f"Max Connections: {self.max_connections}")
            log.debug(f"Timeout: {self.timeout_value}")
            self.connector = TCPConnector(limit=self.max_connections)
            session = self._session = ClientSession(
                connector=self.connector, headers=self.headers, timeout=self.timeout
            )
            self._session_loop = loop

        return session

    @property
    def requests_per_second(self) -> float:
        """Requests per second this client aims for.

        The tier's documented ceiling scaled by :attr:`rate_limit_safety`.
        """
        ceiling = self.patreon_type.requests_per_second() * self.rate_limit_safety
        return max(ceiling, MIN_REQUESTS_PER_SECOND)

    def configure_limiter(self):
        """Build a smoothed rate limiter for the current patreon tier.

        Uses a single-token bucket refilling every ``1 / rps`` seconds rather
        than an ``rps``-token bucket refilling every second. The latter grants
        a full burst, so it can emit ``rps`` requests at the end of one refill
        window and ``rps`` more at the start of the next -- up to ``2 * rps``
        inside a *sliding* second, which is what ballchasing measures. That
        overshoot is why a halved rate was previously needed to avoid 429s.
        """
        if self._external_limiter is not None:
            self.limiter = self._external_limiter
            return

        period = 1 / self.requests_per_second
        existing = getattr(self, "limiter", None)
        if (
            existing is not None
            and existing.max_rate == 1
            and existing.time_period == period
        ):
            # Swapping in an equivalent limiter would let callers already
            # waiting on the old one through alongside the new one's capacity,
            # briefly doubling the rate. Nothing changed, so keep it.
            return

        log.debug(f"Requests per second: {self.requests_per_second}")
        self.limiter = AsyncLimiter(1, period)

    async def _request(
        self,
        url_or_endpoint: str,
        method: str,
        data_factory: RequestDataFactory | None = None,
        **params,
    ) -> "ClientResponse":
        """
        Helper method for all requests.

        :param url: url or endpoint for request.
        :param method: name of the ClientSession method to use, e.g. "get".
                       Resolved against the session at request time so the
                       session can be created lazily.
        :param params: parameters for GET request.
        :return: the request result.
        """
        url = (
            f"{self.base_url}{url_or_endpoint}"
            if url_or_endpoint.startswith("/")
            else url_or_endpoint
        )
        retries = 0
        rate_limit_retries = 0
        while True:
            request_params = dict(params)
            # A None query value means "not set" throughout this client, but
            # yarl raises TypeError rather than dropping it. Filtering here
            # covers every endpoint instead of each one remembering to.
            query = request_params.get("params")
            if query is not None:
                request_params["params"] = {
                    k: v for k, v in query.items() if v is not None
                }

            cleanup = None
            if data_factory is not None:
                request_params["data"], cleanup = data_factory()

            try:
                log.debug(f"Ballchasing request: {url} {request_params}")
                if request_params.get("data") is not None:
                    util.log_form_data(request_params["data"])
                self.total_requests += 1
                # Resolved per attempt so a session rebuilt between retries is
                # picked up rather than a stale bound method being reused.
                session = await self._ensure_session()
                bound_method = getattr(session, method)
                async with self.limiter:
                    r: ClientResponse = await bound_method(url, **request_params)
            except ConnectionError:
                log.exception("Connection error, trying again in 10 seconds...")
                await asyncio.sleep(10)
                retries += 1
                if retries >= RETRY_COUNT:
                    raise
                continue
            except TimeoutError:
                log.exception("Connection to ballchasing timed out.")
                raise
            finally:
                if cleanup is not None:
                    cleanup()

            log.debug(f"Response Status: {r.status}")
            if 200 <= r.status < 300:
                return r
            elif r.status == 429:
                # Don't loop forever on rate limit.
                rate_limit_retries += 1
                self.rate_limit_count += 1
                if rate_limit_retries > MAX_BACKOFF_ATTEMPTS:
                    raise BackoffLimitExceeded(
                        f"Ballchasing is very busy, exceeded maximum attempts ({rate_limit_retries}). Please try again later."
                    )

                if self.print_on_rate_limit:
                    log.warning(f"429 {url} {self.rate_limit_count}")

                sleep_time = self._backoff_delay(r, rate_limit_retries)
                if sleep_time > 0:
                    log.debug(
                        f"Rate limited by ballchasing. Sleeping for {sleep_time:.3f} seconds "
                        f"(Retry: {rate_limit_retries} Backoff: {BACKOFF_MULTIPLIER})"
                    )
                    await asyncio.sleep(sleep_time)
                    log.debug("Woke up from rate limit sleep")
            elif r.status == 400:
                err = await r.json()
                log.error(err.get("error"))
                raise UserFault(err)
            elif r.status == 401:
                raise MissingAPIKey
            elif r.status == 409:
                err = await r.json()
                log.debug(f"Duplicate Replay - {err.get('id')} ({err.get('location')})")
                raise DuplicateReplay(err)
            elif r.status == 500:
                err = await r.json()
                log.error(err.get("error"))
                raise BallchasingFault(err)
            else:
                r.raise_for_status()

    def _backoff_delay(self, response: "ClientResponse", attempt: int) -> float:
        """Seconds to wait before retrying a rate-limited request.

        Prefers the server's ``Retry-After`` when present, otherwise backs off
        exponentially from :attr:`sleep_time_on_rate_limit`.

        Jitter matters more than usual here: concurrent callers are typically
        rate limited within the same instant, so waking them all on the same
        schedule just reproduces the burst that caused the 429.
        """
        retry_after = util.parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            base = retry_after
        else:
            base = self.sleep_time_on_rate_limit * (attempt**BACKOFF_MULTIPLIER)

        if base <= 0:
            return 0.0
        # Equal jitter: never wait less than half the backoff, but spread the
        # herd across the second half of the window.
        return base / 2 + random.uniform(0, base / 2)

    async def ping(self) -> models.Ping:
        """
        Use this API to:

        - check if your API key is correct
        - check if ballchasing API is reachable

        This method runs automatically at initialization and the steam name and id as well as patron type are stored.
        :return: ping response.
        """
        resp = await self._request("/", "get")
        result = await resp.json()
        ping = models.Ping(**result)

        self.steam_name = ping.name
        self.steam_id = ping.steam_id
        self.patreon_type = ping.type

        if self._sleep_time_override is None:
            self.sleep_time_on_rate_limit = 1 / self.requests_per_second
        log.debug(f"Sleep time on rate limit: {self.sleep_time_on_rate_limit}")

        # The tier we just learned may differ from the one assumed at
        # construction, so re-derive the rate. This is a no-op when unchanged.
        self.configure_limiter()
        return ping

    async def search(
        self,
        player_name: list[str] | None = None,
        player_id: list[str] | None = None,
        title: str | None = None,
        playlist: list[Playlist] | None = None,
        season: list[str] | None = None,
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
        :param player_name: filter replays by a player's name.
        :param player_id: filter replays by a player's platform id in the $platform:$id, e.g. steam:76561198141161044,
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
            # str(None).lower() is "none", which survives the None filter below
            # and would send a literal pro=none to the API.
            "pro": None if pro is None else str(pro).lower(),
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
        params = {k: v for k, v in params.items() if v is not None}
        resp = await self._request(url, "get", params=params)
        data = await resp.json()
        return models.ReplaySearch(**data)

    async def get_replays(
        self,
        player_name: list[str] | None = None,
        player_id: list[str] | None = None,
        title: str | None = None,
        playlist: list[Playlist] | None = None,
        season: list[str] | None = None,
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
        :param player_name: filter replays by a player's name.
        :param player_id: filter replays by a player's platform id in the $platform:$id, e.g. steam:76561198141161044,
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
        params = {k: v for k, v in params.items() if v is not None}

        left = count
        while left > 0:
            request_count = min(left, 200)
            params["count"] = request_count
            resp = await self._request(url, "get", params=params)
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

            # Pydantic hands back AnyHttpUrl; _request takes a plain str.
            url = str(replays.next)
            left -= len(replays.list)
            params = {}

    async def get_replay(self, replay_id: str) -> models.Replay:
        """
        Retrieve a given replay's details and stats.

        :param replay_id: the replay id.
        :return: the result of the GET request.
        """
        r = await self._request(f"/replays/{replay_id}", "get")
        data = await r.json()
        return models.Replay(**data)

    async def patch_replay(self, replay_id: str, **params) -> None:
        """
        This endpoint can patch one or more fields of the specified replay

        :param replay_id: the replay id.
        :param params: parameters for the PATCH request.
        """
        await self._request(f"/replays/{replay_id}", "patch", json=params)

    async def upload_replay(
        self,
        replay_file: str,
        visibility: Visibility = Visibility.PUBLIC,
        group: str | None = None,
    ) -> models.ReplayCreated:
        """
        Use this API to upload a replay file to ballchasing.com.

        :param replay_file: replay file to upload.
        :param visibility: to set the visibility of the uploaded replay. (Default: Public)
        :param group: assign replay to a specific group id
        :return: the result of the POST request.
        """

        def build_form_data() -> tuple[FormData, Callable[[], None]]:
            files = FormData()
            # Not a context manager on purpose: aiohttp streams from this
            # handle while the request is in flight, so it has to outlive this
            # function. _request closes it via the returned cleanup callback,
            # including on retries, where each attempt needs a fresh handle.
            replay_handle = open(replay_file, "rb")  # noqa: SIM115
            files.add_field(
                "file",
                replay_handle,
                filename=replay_file,
            )
            return files, replay_handle.close

        r = await self._request(
            "/v2/upload",
            "post",
            data_factory=build_form_data,
            params={"visibility": visibility, "group": group},
        )
        data = await r.json()

        if r.status == 409:
            raise DuplicateReplay(data)
        return models.ReplayCreated(**data)

    async def upload_replay_from_bytes(
        self,
        name: str,
        replay_data: bytes,
        visibility: Visibility = Visibility.PUBLIC,
        group: str | None = None,
    ) -> models.ReplayCreated:
        """
        Use this API to upload a replay file to ballchasing.com.

        :param name: Desired name of file (Can be anything).
        :param replay_data: bytes like object to be uploaded.
        :param visibility: to set the visibility of the uploaded replay. (Default: Public)
        :param group: assign replay to a specific group id
        :return: the result of the POST request.
        """

        def build_form_data() -> tuple[FormData, None]:
            files = FormData()
            files.add_field(
                "file",
                replay_data,
                filename=name,
            )
            return files, None

        r = await self._request(
            "/v2/upload",
            "post",
            data_factory=build_form_data,
            params={"visibility": visibility, "group": group},
        )

        data = await r.json()
        if r.status == 409:
            raise DuplicateReplay(data)
        return models.ReplayCreated(**data)

    async def delete_replay(self, replay_id: str) -> None:
        """
        This endpoint deletes the specified replay.
        WARNING: This operation is permanent and undoable.

        :param replay_id: the replay id.
        """
        await self._request(f"/replays/{replay_id}", "delete")

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
        params = {k: v for k, v in params.items() if v is not None}

        left = count
        while left > 0:
            request_count = min(left, 200)
            params["count"] = request_count
            resp = await self._request(url, "get", params=params)
            data = await resp.json()
            groups = models.GroupSearch(**data)

            # yield from batch
            for g in groups.list:
                yield g

            if not groups.next:
                break

            # Pydantic hands back AnyHttpUrl; _request takes a plain str.
            url = str(groups.next)
            left -= len(groups.list)
            params = {}

    async def create_group(
        self,
        name: str,
        player_identification: PlayerIdentificationBy,
        team_identification: TeamIdentificationBy,
        parent: str | None = None,
    ) -> models.GroupCreated:
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
        r = await self._request("/groups", "post", json=json)
        data = await r.json()
        result = models.GroupCreated(**data)
        return result

    async def get_group(self, group_id: str) -> models.ReplayGroup:
        """
        This endpoint retrieves a specific replay group info and stats given its id.

        :param group_id: the group id.
        :return: the group info with stats.
        """
        r = await self._request(f"/groups/{group_id}", "get")
        data = await r.json()
        return models.ReplayGroup(**data)

    async def patch_group(self, group_id: str, **params) -> None:
        """
        This endpoint can patch one or more fields of the specified group.

        :param group_id: the group id
        :param params: parameters for the PATCH request.
        """
        await self._request(f"/groups/{group_id}", "patch", json=params)

    async def delete_group(self, group_id: str) -> None:
        """
        This endpoint deletes the specified group.
        WARNING: This operation is permanent and undoable.

        :param group_id: the group id.
        """
        await self._request(f"/groups/{group_id}", "delete")

    async def get_group_replays(
        self, group_id: str, deep: bool = False, recurse: bool = False
    ) -> AsyncIterator[models.Replay]:
        """
        Finds all replays in a group, including child groups.

        :param group_id: the base group id.
        :param deep: whether or not to get full stats for each replay (will be much slower).
        :return: an iterator over all the replays in the group.
        """
        if recurse:
            # Descend first, then fall through to this group's own replays.
            # Recursing *instead* of fetching would mean no level ever calls
            # get_replays, so the iterator could never yield anything.
            async for child in self.get_groups(group=group_id):
                async for replay in self.get_group_replays(
                    child.id, deep, recurse=True
                ):
                    yield replay

        async for replay in self.get_replays(group_id=group_id, deep=deep):
            yield replay

    async def download_replay(self, replay_id: str, folder: str) -> None:
        """
        Download a replay file.

        :param replay_id: the replay id.
        :param folder: the folder to download into.
        """
        r = await self._request(f"/replays/{replay_id}/file", "get")
        async with aiofiles.open(f"{folder}/{replay_id}.replay", mode="wb") as fd:
            await fd.write(await r.read())

    async def download_replay_content(self, replay_id: str) -> bytes:
        """
        Download a replay file contents

        :param replay_id: the replay id.
        """
        r = await self._request(f"/replays/{replay_id}/file", "get")
        return await r.read()

    async def download_group(
        self, group_id: str, folder: str, recursive=True
    ) -> tuple[int, int]:
        """
        Download an entire group.

        :param group_id: the base group id.
        :param folder: the folder in which to create the group folder.
        :param recursive: whether or not to create new folders for child groups.
        """
        folder = os.path.join(folder, group_id)
        group_count = 0
        replay_count = 0
        log.debug("Downloading group %s into %s", group_id, folder)
        if recursive:
            os.makedirs(folder, exist_ok=True)
            async for child_group in self.get_groups(group=group_id):
                child_group_count, child_replay_count = await self.download_group(
                    child_group.id, folder, recursive=True
                )
                group_count += child_group_count + 1
                replay_count += child_replay_count
            async for replay in self.get_replays(group_id=group_id):
                log.debug("Downloading replay %s", replay.id)
                replay_count += 1
                await self.download_replay(replay.id, folder)
        else:
            async for replay in self.get_group_replays(group_id, recurse=False):
                log.debug("Downloading replay %s", replay.id)
                group_count += 1
                replay_count += 1
                await self.download_replay(replay.id, folder)
        return group_count, replay_count

    async def get_maps(self):
        """
        Use this API to get the list of map codes to map names (map as in stadium).
        """
        res = await self._request("/maps", "get")
        return await res.json()

    async def close(self):
        session = self._session
        self._session = None
        self._session_loop = None
        self.connector = None

        if session is None or session.closed:
            return
        await session.close()
        # Wait a bit for connections to close properly
        await asyncio.sleep(0.5)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        return False

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
