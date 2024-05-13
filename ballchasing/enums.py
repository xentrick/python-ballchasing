from typing import Literal, get_args
from enum import Enum, StrEnum, IntEnum

class ReplayStatus(StrEnum):
    OK = "ok"
    PENDING = "pending"
    FAILED = "failed"

class Playlist(StrEnum):
    DUELS = "ranked-duels"
    DOUBLES = "ranked-doubles"
    SOLO_STANDARD = "ranked-solo-standard"
    STANDARD = "ranked-standard"
    UNRANKED_DUELS = "unranked-duels"
    UNRANKED_DOUBLES = "unranked-doubles"
    UNRANKED_STANDARD = "unranked-standard"
    PRIVATE = "private"
    SEASON = "season"
    OFFLINE = "offline"
    ROCKETLABS = "rocket-labs"
    HOOPS = "ranked-hoops"
    RUMBLE = "ranked-rumble"
    DROPSHOT = "ranked-dropshot"
    SNOWDAY = "ranked-snowday"
    UNRANKED_HOOPS = "hoops"
    UNRANKED_RUMBLE = "rumble"
    UNRANKED_DROPSHOT = "dropshot"
    UNRANKED_SNOWDAY = "snowday"
    TOURNAMENT = "tournament"
    DROPSHOT_RUMBLE = "dropshot-rumble"
    HEATSEEKER = "heatseeker"

class Rank(StrEnum):
    UNRANKED = "unranked"
    BRONZE1 = "bronze-1"
    BRONZE2 = "bronze-2"
    BRONZE3 = "bronze-3"
    SILVER1 = "silver-1"
    SILVER2 = "silver-2"
    SILVER3 = "silver-3"
    GOLD1 = "gold-1"
    GOLD2 = "gold-2"
    GOLD3 = "gold-3"
    PLAT1 = "platinum-1"
    PLAT2 = "platinum-2"
    PLAT3 = "platinum-3"
    DIAMOND1 = "diamond-1"
    DIAMOND2 = "diamond-2"
    DIAMOND3 = "diamond-3"
    CHAMP1 = "champion-1"
    CHAMP2 = "champion-2"
    CHAMP3 = "champion-3"
    GC = "grand-champion"
    GC1 = "grand-champion-1"
    GC2 = "grand-champion-2"
    GC3 = "grand-champion-3"
    SSL = "supersonic-legend"

class MatchResult(StrEnum):
    WIN = "win"
    LOSS = "loss"

class ReplaySortBy(StrEnum):
    REPLAY_DATE = "replay-date"
    UPLOAD_DATE = "upload-date"


class GroupSortBy(StrEnum):
    CREATED = "created"
    name = "name"


class SortDir(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"

class Visibility(StrEnum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"

class PlayerIdentificationBy(StrEnum):
    ID = "by-id"
    NAME = "by-name"

class TeamIdentificationBy(StrEnum):
    DISTINCT = "by-distinct-players"
    CLUSTERS = "by-player-clusters"

class PatreonType(StrEnum):
    REGULAR = "regular"
    GOLD = "gold"
    DIAMOND = "diamond"
    CHAMPION = "champion"
    GC = "gc"
    LEGEND = "legend"
    ORG = "org"

    def rate_limit(self) -> float:
        match self:
            case PatreonType.REGULAR:
                return 3600 / 1000
            case PatreonType.GOLD:
                return 3600 / 2000
            case PatreonType.DIAMOND:
                return 3600 / 5000
            case PatreonType.CHAMPION:
                return 1 / 8
            case PatreonType.GC:
                return 1 / 16
            case PatreonType.LEGEND:
                return 1 / 32
            case PatreonType.ORG:
                return 1 / 64
