#!/usr/bin/env python3

import argparse
import asyncio
import os

from dotenv import load_dotenv

import ballchasing
from ballchasing import models
from ballchasing.exceptions import UserFault
from ballchasing.util import parse_group_id

load_dotenv()


async def owned_group(bc: ballchasing.Api, group_id: str, me: models.Ping, role: str):
    """Fetch a group and confirm the authenticated account owns it.

    Ballchasing lets you read groups you don't own, but rejects both a parent
    and a target you don't own - with a bare "no such parent" / 404 rather than
    anything actionable.
    """
    group = await bc.get_group(group_id)
    owner = group.creator
    if owner and str(owner.steam_id) != str(me.steam_id):
        raise SystemExit(
            f"{role} group '{group.name}' is owned by {owner.name} "
            f"({owner.steam_id}), not by {me.name} ({me.steam_id}).\n"
            "Ballchasing only lets you restructure groups your own account "
            "owns - use that account's API key."
        )
    return group


async def move_group(key: str, group_id: str, parent: str | None) -> None:
    async with ballchasing.Api(auth_key=key, timeout=30) as bc:
        me = await bc.ping()
        print(f"Authenticated as {me.name} ({me.steam_id})")

        group = await owned_group(bc, group_id, me, "Target")
        print(f"Moving: {group.name} ({group.id})")

        if parent is None:
            print("New parent: (none - moving to top level)")
        else:
            parent_group = await owned_group(bc, parent, me, "Parent")
            print(f"New parent: {parent_group.name} ({parent_group.id})")

        # Ballchasing takes an empty string to mean "detach from any parent".
        try:
            await bc.patch_group(group.id, parent="" if parent is None else parent)
        except UserFault as e:
            raise SystemExit(f"Ballchasing rejected the move: {e}") from e

        if parent is None:
            print("Moved to top level")
        else:
            children = [c async for c in bc.get_groups(group=parent, count=200)]
            if any(c.id == group.id for c in children):
                print(f"Moved. {group.link}")
            else:
                raise SystemExit(
                    f"PATCH succeeded but '{group.name}' is not listed under "
                    f"{parent}. Check the group on ballchasing.com."
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Move an existing ballchasing replay group under a "
        "different parent group (or to the top level)."
    )
    parser.add_argument("group", type=str, help="Group id or URL to move")
    parser.add_argument(
        "-p",
        "--parent",
        type=str,
        default=None,
        help="New parent group id or URL",
    )
    parser.add_argument(
        "--root",
        action="store_true",
        help="Detach the group from its parent instead of moving it under another",
    )
    argv = parser.parse_args()

    if bool(argv.parent) == argv.root:
        parser.error("Pass either --parent GROUP or --root, not both/neither")

    key = os.getenv("BALLCHASING_KEY")
    if not key:
        raise ValueError("Missing BALLCHASING_KEY in .env file")

    parent = None if argv.root else parse_group_id(argv.parent)

    asyncio.run(move_group(key, parse_group_id(argv.group), parent))
