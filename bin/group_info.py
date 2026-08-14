#!/usr/bin/env python3

import argparse
import asyncio
import os

from dotenv import load_dotenv

import ballchasing
from ballchasing import models
from ballchasing.util import parse_group_id

load_dotenv()


def field(label: str, value) -> None:
    print(f"  {label + ':':<24}{value}")


def print_group(group: models.ReplayGroup) -> None:
    print(f"{group.name}")
    field("ID", group.id)
    field("Link", group.link)
    field("Created", group.created.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"))
    if group.creator:
        field("Creator", f"{group.creator.name} ({group.creator.steam_id})")
    if group.user:
        field("Uploader", f"{group.user.name} ({group.user.steam_id})")

    print("\nSettings")
    field("Player identification", group.player_identification)
    field("Team identification", group.team_identification)
    field("Shared", group.shared)
    if group.status:
        field("Status", group.status)

    print("\nContents")
    field("Direct replays", group.direct_replays if group.direct_replays is not None else 0)
    field("Indirect replays", group.indirect_replays if group.indirect_replays is not None else 0)
    field("Teams", len(group.teams))
    field("Players", len(group.players))
    if group.failed_replays:
        field("Failed replays", len(group.failed_replays))
        for replay_id in group.failed_replays:
            print(f"    {replay_id}")


def print_teams(group: models.ReplayGroup) -> None:
    if not group.teams and not group.players:
        return

    print("\nTeams")
    for team in group.teams:
        print(f"  {team.name}")
        for player in team.players:
            print(f"    {player.name} ({player.platform}:{player.id})")

    unassigned = [p for p in group.players if not p.team]
    if unassigned:
        print("  (no team)")
        for player in unassigned:
            print(f"    {player.name} ({player.platform}:{player.id})")


async def group_info(key: str, group_id: str, show_teams: bool, as_json: bool) -> None:
    async with ballchasing.Api(auth_key=key, timeout=30) as bc:
        group = await bc.get_group(group_id)

        if as_json:
            print(group.model_dump_json(indent=2, exclude={"teams", "players"}))
            return

        print_group(group)
        if show_teams:
            print_teams(group)

        children = [child async for child in bc.get_groups(group=group_id, count=200)]
        print("\nSub groups")
        if not children:
            print("  (none)")
        for child in children:
            direct = child.direct_replays or 0
            indirect = child.indirect_replays or 0
            print(f"  {child.name}")
            print(f"    {child.id}  ({direct} direct / {indirect} indirect replays)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Show settings and metadata for a ballchasing replay group, "
        "including its sub groups."
    )
    parser.add_argument("group", type=str, help="Ballchasing group id or URL")
    parser.add_argument(
        "-t",
        "--teams",
        action="store_true",
        help="Also list the teams and players tracked in the group",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Dump the raw group payload as JSON (excludes team/player stats)",
    )
    argv = parser.parse_args()

    key = os.getenv("BALLCHASING_KEY")
    if not key:
        raise ValueError("Missing BALLCHASING_KEY in .env file")

    asyncio.run(group_info(key, parse_group_id(argv.group), argv.teams, argv.json))
