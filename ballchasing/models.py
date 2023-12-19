from pydantic import BaseModel, AnyHttpUrl , ConfigDict
from datetime import datetime
from ballchasing.enums import PatreonType, Playlist, Rank, PlayerIdentificationBy, TeamIdentificationBy

class BallchasingModel(BaseModel):
    """Base class from `BaseModel` to implement hash"""

class Uploader(BallchasingModel):
    avatar: AnyHttpUrl
    name: str
    profile_url: AnyHttpUrl
    steam_id: int

class PlayerRank(BallchasingModel):
    division: int | None
    id: Rank
    name: str
    tier: int
class Platform(BallchasingModel):
    id: str | None
    platform: str | None

class CameraSettings(BallchasingModel):
    distance: int
    fov: int
    height: int
    pitch: int
    stiffness: float
    swivel_speed: float
    transition_speed: float

class CoreStats(BallchasingModel):
    assists: int
    goals_against: int
    goals: int
    mvp: bool | None
    saves: int
    score: int
    shooting_percentage: int
    shots_against: int
    shots: int

class BoostStats(BallchasingModel):
    amount_collected_big: int
    amount_collected_small: int
    amount_collected: int
    amount_overfill_stolen: int
    amount_overfill: int
    amount_stolen_big: int
    amount_stolen_small: int
    amount_stolen: int
    amount_used_while_supersonic: int
    avg_amount: float | None
    bcpm: float | None
    bpm: int | None
    count_collected_big: int
    count_collected_small: int
    count_stolen_big: int
    count_stolen_small: int
    percent_boost_0_25: float | None
    percent_boost_25_50: float | None
    percent_boost_50_75: float | None
    percent_boost_75_100: float | None
    percent_full_boost: float | None
    percent_zero_boost: float | None
    time_boost_0_25: float
    time_boost_25_50: float
    time_boost_50_75: float
    time_boost_75_100: float
    time_full_boost: float
    time_zero_boost: float

class MovementStats(BallchasingModel):
    avg_powerslide_duration: float | None
    avg_speed_percentage: float | None
    avg_speed: int | None
    count_powerslide: int
    percent_boost_speed: float | None
    percent_ground: float | None
    percent_high_air: float | None
    percent_low_air: float | None
    percent_slow_speed: float | None
    percent_supersonic_speed: float | None
    time_boost_speed: float
    time_ground: float
    time_high_air: float
    time_low_air: float
    time_powerslide: float
    time_slow_speed: float
    time_supersonic_speed: float
    total_distance: int | None

class PositioningStats(BallchasingModel):
    avg_distance_to_ball_no_possession: int | None
    avg_distance_to_ball_possession: int | None
    avg_distance_to_ball: int | None
    avg_distance_to_mates: int | None
    percent_behind_ball: float |  None
    percent_closest_to_ball: float |  None
    percent_defensive_half: float |  None
    percent_defensive_third: float |  None
    percent_farthest_from_ball: float |  None
    percent_infront_ball: float |  None
    percent_most_back: float |  None
    percent_most_forward: float |  None
    percent_neutral_third: float |  None
    percent_offensive_half: float |  None
    percent_offensive_third: float |  None
    time_behind_ball: float
    time_closest_to_ball: int | None
    time_defensive_half: float
    time_defensive_third: float
    time_farthest_from_ball: int | None
    time_infront_ball: float
    time_most_back: int | None
    time_most_forward: int | None
    time_neutral_third: float
    time_offensive_half: float
    time_offensive_third: float

class DemoStats(BallchasingModel):
    inflicted: int
    taken: int

class BallStats(BallchasingModel):
    time_in_side: float | None
    possession_time: float | None

class Stats(BallchasingModel):
    ball: BallStats | None
    boost: BoostStats
    core: CoreStats
    demo: DemoStats
    movement: MovementStats
    positioning: PositioningStats

class Player(BallchasingModel):
    camera: CameraSettings | None
    car_id: int | None
    car_name: str | None
    end_time: float
    id: Platform
    mvp: bool | None
    pro: bool | None
    rank: PlayerRank | None
    start_time: float
    stats: Stats | None
    steering_sensitivity: float | None


class Team(BallchasingModel):
    color: str | None
    name: str | None
    players: list[Player] = []
    stats: Stats | None

class Replay(BallchasingModel):
    blue: Team
    created: datetime
    date_has_timezone: bool | None
    date: datetime
    duration: int
    id: str
    link: AnyHttpUrl
    map_code: str
    map_name: str | None
    match_guid: str | None
    match_type: str | None
    max_rank: PlayerRank | None
    min_rank: PlayerRank | None
    orange: Team
    overtime: bool
    playlist_id: Playlist | None
    playlist_name: str | None
    replay_title: str | None
    rocket_league_id: str
    season: int
    season_type: str | None
    status: str | None
    team_size: int | None
    title: str | None
    uploader: Uploader
    visibility: str

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
    count: int | None
    list: list[Replay]
    next: AnyHttpUrl | None


class Creator(BallchasingModel):
    steam_id: str
    name: str
    profile_url: AnyHttpUrl
    avatar: AnyHttpUrl
    avatar_full: str | None
    avatar_medium: str | None

class Cumulative(BallchasingModel):
    games: int
    wins: int
    win_percentage: int
    play_duration: int
    core: CoreStats
    boost: BoostStats
    movement: MovementStats
    positioning: PositioningStats
    demo: DemoStats

class GameAverage(BallchasingModel):
    core: CoreStats
    boost: BoostStats
    movement: MovementStats
    positioning: PositioningStats
    demo: DemoStats

class GroupPlayers(BallchasingModel):
    platform: str
    id: str
    name: str
    team: str
    cumulative: Cumulative
    game_average: GameAverage

class TeamPlayers(BallchasingModel):
    platform: str
    id: str
    name: str
    team: str

class GroupTeams(BallchasingModel):
    name: str
    players: list[TeamPlayers]
    cumulative: Cumulative
    game_average: GameAverage

class ReplayGroup(BallchasingModel):
    id: str
    link: AnyHttpUrl
    name: str
    created: datetime
    status: str | None
    player_identification: PlayerIdentificationBy
    team_identification: TeamIdentificationBy
    direct_replays: int | None
    indirect_replays: int | None
    shared: bool
    creator: Creator | None
    user: Uploader | None
    players: list[GroupPlayers] = []
    teams: list[GroupTeams] = []

class GroupSearch(BallchasingModel):
    count: int | None
    list: list[ReplayGroup]
    next: AnyHttpUrl | None


class GroupCreated(BallchasingModel):
    id: str
    link: AnyHttpUrl

class ReplayCreated(BallchasingModel):
    id: str
    link: AnyHttpUrl