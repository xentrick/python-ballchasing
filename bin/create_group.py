#!/usr/bin/env python3

import argparse
import asyncio
import os

from dotenv import load_dotenv

import ballchasing
from ballchasing.enums import PlayerIdentificationBy, TeamIdentificationBy
from ballchasing.util import parse_group_id

load_dotenv()


async def create_group(
    key: str,
    name: str,
    player_identification: PlayerIdentificationBy,
    team_identification: TeamIdentificationBy,
    parent: str | None,
    allow_duplicate: bool,
) -> None:
    async with ballchasing.Api(auth_key=key, timeout=30) as bc:
        me = await bc.ping()
        print(f"Authenticated as {me.name} ({me.steam_id})")

        if parent:
            # Fails loudly here rather than with an opaque API error on POST.
            parent_group = await bc.get_group(parent)
            print(f"Parent group: {parent_group.name} ({parent_group.id})")

            # Ballchasing lets you *read* any group you have access to, but
            # only accepts a parent the API key's own account owns. Without
            # this check the POST comes back as a bare "no such parent".
            owner = parent_group.creator
            if owner and str(owner.steam_id) != str(me.steam_id):
                raise SystemExit(
                    f"Parent group '{parent_group.name}' is owned by "
                    f"{owner.name} ({owner.steam_id}), not by {me.name} "
                    f"({me.steam_id}).\nBallchasing only allows creating a sub "
                    "group under a group your own account owns - use that "
                    "account's API key, or pick a parent you own."
                )

        if not allow_duplicate:
            existing = [
                g
                async for g in bc.get_groups(
                    name=name, group=parent, creator="me", count=200
                )
                if g.name == name
            ]
            if existing:
                print(f"Group '{name}' already exists:")
                for g in existing:
                    print(f"  {g.id} {g.link}")
                print("Pass --allow-duplicate to create another one anyway.")
                return

        created = await bc.create_group(
            name=name,
            player_identification=player_identification,
            team_identification=team_identification,
            parent=parent,
        )
        print(f"Created group: {created.id}")
        print(f"Link: {created.link}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create an RSC replay group on ballchasing.com, optionally "
        "as a sub group of an existing group."
    )
    parser.add_argument("name", type=str, help="Name of the new group")
    parser.add_argument(
        "-p",
        "--parent",
        type=str,
        default=None,
        help="Parent group id or URL. The new group is created as its sub group",
    )
    parser.add_argument(
        "--player-identification",
        type=PlayerIdentificationBy,
        choices=list(PlayerIdentificationBy),
        default=PlayerIdentificationBy.ID,
        help="How to identify the same player across replays (default: by-id)",
    )
    parser.add_argument(
        "--team-identification",
        type=TeamIdentificationBy,
        choices=list(TeamIdentificationBy),
        default=TeamIdentificationBy.DISTINCT,
        help="How to identify the same team across replays (default: by-distinct-players)",
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Create the group even if one with the same name already exists",
    )
    argv = parser.parse_args()

    key = os.getenv("BALLCHASING_KEY")
    if not key:
        raise ValueError("Missing BALLCHASING_KEY in .env file")

    parent = parse_group_id(argv.parent) if argv.parent else None

    asyncio.run(
        create_group(
            key,
            argv.name,
            argv.player_identification,
            argv.team_identification,
            parent,
            argv.allow_duplicate,
        )
    )
