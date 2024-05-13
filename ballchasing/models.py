from pydantic import BaseModel, AnyHttpUrl, ConfigDict
from datetime import datetime
from ballchasing.enums import (
    PatreonType,
    Playlist,
    Rank,
    PlayerIdentificationBy,
    TeamIdentificationBy,
    ReplayStatus,
    Visibility,
)

class BallchasingModel(BaseModel):
    """Base class from `BaseModel` to implement hash"""


class Uploader(BallchasingModel):
    avatar: AnyHttpUrl
    name: str
    profile_url: AnyHttpUrl
    steam_id: int


class PlayerRank(BallchasingModel):
    division: int | None = None
    id: Rank
    name: str
    tier: int


class Platform(BallchasingModel):
    id: str | None = None
    platform: str | None = None


class CameraSettings(BallchasingModel):
    distance: int
    fov: int
    height: int
    pitch: int
    stiffness: float
    swivel_speed: float
    transition_speed: float


class CoreStats(BallchasingModel):
    assists: float
    goals_against: float
    goals: float
    mvp: bool | None = None
    saves: float
    score: float
    shooting_percentage: float
    shots_against: float
    shots: float


class BoostStats(BallchasingModel):
    amount_collected_big: float
    amount_collected_small: float
    amount_collected: float
    amount_overfill_stolen: float
    amount_overfill: float
    amount_stolen_big: float
    amount_stolen_small: float
    amount_stolen: float
    amount_used_while_supersonic: float
    avg_amount: float | None = None
    bcpm: float | None = None
    bpm: float | None = None
    count_collected_big: float
    count_collected_small: float
    count_stolen_big: float
    count_stolen_small: float
    percent_boost_0_25: float | None = None
    percent_boost_25_50: float | None = None
    percent_boost_50_75: float | None = None
    percent_boost_75_100: float | None = None
    percent_full_boost: float | None = None
    percent_zero_boost: float | None = None
    time_boost_0_25: float
    time_boost_25_50: float
    time_boost_50_75: float
    time_boost_75_100: float
    time_full_boost: float
    time_zero_boost: float


class MovementStats(BallchasingModel):
    avg_powerslide_duration: float | None = None
    avg_speed_percentage: float | None = None
    avg_speed: float | None = None
    count_powerslide: float
    percent_boost_speed: float | None = None
    percent_ground: float | None = None
    percent_high_air: float | None = None
    percent_low_air: float | None = None
    percent_slow_speed: float | None = None
    percent_supersonic_speed: float | None = None
    time_boost_speed: float
    time_ground: float
    time_high_air: float
    time_low_air: float
    time_powerslide: float
    time_slow_speed: float
    time_supersonic_speed: float
    total_distance: float | None = None


class PositioningStats(BallchasingModel):
    avg_distance_to_ball_no_possession: float | None = None
    avg_distance_to_ball_possession: float | None = None
    avg_distance_to_ball: float | None = None
    avg_distance_to_mates: int | None = None
    percent_behind_ball: float | None = None
    percent_closest_to_ball: float | None = None
    percent_defensive_half: float | None = None
    percent_defensive_third: float | None = None
    percent_farthest_from_ball: float | None = None
    percent_infront_ball: float | None = None
    percent_most_back: float | None = None
    percent_most_forward: float | None = None
    percent_neutral_third: float | None = None
    percent_offensive_half: float | None = None
    percent_offensive_third: float | None = None
    time_behind_ball: float
    time_closest_to_ball: float | None = None
    time_defensive_half: float
    time_defensive_third: float
    time_farthest_from_ball: float | None = None
    time_infront_ball: float
    time_most_back: float | None = None
    time_most_forward: float | None = None
    time_neutral_third: float
    time_offensive_half: float
    time_offensive_third: float


class DemoStats(BallchasingModel):
    inflicted: float
    taken: float


class BallStats(BallchasingModel):
    time_in_side: float | None = None
    possession_time: float | None = None


class Stats(BallchasingModel):
    ball: BallStats | None = None
    boost: BoostStats
    core: CoreStats
    demo: DemoStats
    movement: MovementStats
    positioning: PositioningStats


class Player(BallchasingModel):
    camera: CameraSettings | None = None
    car_id: int | None = None
    car_name: str | None = None
    end_time: float
    id: Platform
    mvp: bool | None = None
    name: str
    pro: bool | None = None
    rank: PlayerRank | None = None
    start_time: float
    stats: Stats | None = None
    steering_sensitivity: float | None = None


class Team(BallchasingModel):
    color: str | None = None
    name: str | None = None
    players: list[Player] = []
    stats: Stats | None = None


class Replay(BallchasingModel):
    blue: Team | None = None
    created: datetime
    date_has_timezone: bool | None = None
    date: datetime | None = None
    duration: int | None = None
    id: str
    link: AnyHttpUrl
    map_code: str | None = None
    map_name: str | None = None
    match_guid: str | None = None
    match_type: str | None = None
    max_rank: PlayerRank | None = None
    min_rank: PlayerRank | None = None
    orange: Team | None = None
    overtime: bool | None = None
    playlist_id: Playlist | None = None
    playlist_name: str | None = None
    replay_title: str | None = None
    rocket_league_id: str | None = None
    season: int | None = None
    season_type: str | None = None
    status: ReplayStatus | None = None
    team_size: int | None = None
    title: str | None = None
    uploader: Uploader
    visibility: Visibility | None = None

    def __hash__(self):
        if self.match_guid:
            return hash(self.match_guid)
        else:
            return hash(self.id)

    def __eq__(self, other):
        if not isinstance(other, Replay):
            raise ValueError("Must be a ballchasing replay")

        # Same replay regardless of uploader
        if self.match_guid == other.match_guid:
            return True

        # Ballchasing ID fallback
        if self.id == other.id:
            return True
        return False


class Ping(BallchasingModel):
    ball: str
    boost: str
    chaser: bool
    chat: dict[str, str]
    name: str
    steam_id: str
    type: PatreonType


class ReplaySearch(BallchasingModel):
    count: int | None = None
    list: list[Replay]
    next: AnyHttpUrl | None = None


class Creator(BallchasingModel):
    avatar_full: str | None = None
    avatar_medium: str | None = None
    avatar: AnyHttpUrl
    name: str
    profile_url: AnyHttpUrl
    steam_id: str


class Cumulative(BallchasingModel):
    boost: BoostStats
    core: CoreStats
    demo: DemoStats
    games: int
    movement: MovementStats
    play_duration: int
    positioning: PositioningStats
    win_percentage: float
    wins: int


class GameAverage(BallchasingModel):
    boost: BoostStats
    core: CoreStats
    demo: DemoStats
    movement: MovementStats
    positioning: PositioningStats


class GroupPlayers(BallchasingModel):
    cumulative: Cumulative
    game_average: GameAverage
    id: str
    name: str
    platform: str
    team: str


class TeamPlayers(BallchasingModel):
    id: str
    name: str
    platform: str
    team: str


class GroupTeams(BallchasingModel):
    cumulative: Cumulative
    game_average: GameAverage
    name: str
    players: list[TeamPlayers]


class ReplayGroup(BallchasingModel):
    created: datetime
    creator: Creator | None = None
    direct_replays: int | None = None
    failed_replays: list[str] | None = None
    id: str
    indirect_replays: int | None = None
    link: AnyHttpUrl
    name: str
    player_identification: PlayerIdentificationBy
    players: list[GroupPlayers] = []
    shared: bool
    status: str | None = None
    team_identification: TeamIdentificationBy
    teams: list[GroupTeams] = []
    user: Uploader | None = None


class GroupSearch(BallchasingModel):
    count: int | None = None
    list: list[ReplayGroup]
    next: AnyHttpUrl | None = None


class GroupCreated(BallchasingModel):
    id: str
    link: AnyHttpUrl


class ReplayCreated(BallchasingModel):
    id: str
    link: AnyHttpUrl | None = None
