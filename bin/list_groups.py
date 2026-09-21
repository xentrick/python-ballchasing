#!/usr/bin/env python3

import argparse
import asyncio
import json
import os

from dotenv import load_dotenv

import ballchasing
from ballchasing import models
from ballchasing.enums import GroupSortBy, SortDir
from ballchasing.util import parse_group_id

load_dotenv()

WEB_URL = "https://ballchasing.com/group/{}"


def web_link(group: models.ReplayGroup) -> str:
    """The browser URL for a group.

    ``group.link`` is the *API* url the search endpoint hands back; the one
    worth pasting anywhere else is the /group/<id> page.
    """
    return WEB_URL.format(group.id)


def print_group(group: models.ReplayGroup, subgroups: int | None) -> None:
    direct = group.direct_replays or 0
    indirect = group.indirect_replays or 0

    print(group.name)
    print(f"  {group.id}")
    print(f"  {web_link(group)}")
    print(
        f"  created {group.created.astimezone().strftime('%Y-%m-%d %H:%M')}"
        f"  |  {direct} direct / {indirect} total replays"
        f"  |  {'shared' if group.shared else 'private'}"
    )
    if subgroups is not None:
        print(f"  {subgroups} sub group{'' if subgroups == 1 else 's'}")


async def list_groups(
    key: str,
    parent: str | None,
    name: str | None,
    count: int,
    sort_by: GroupSortBy,
    sort_dir: SortDir,
    created_after: str | None,
    created_before: str | None,
    show_subgroups: bool,
    as_json: bool,
) -> None:
    async with ballchasing.Api(auth_key=key, timeout=30) as bc:
        if not as_json:
            me = await bc.ping()
            print(f"Authenticated as {me.name} ({me.steam_id})\n")

            if parent:
                parent_group = await bc.get_group(parent)
                print(f"Sub groups of {parent_group.name} ({parent_group.id})")
                print(f"  {web_link(parent_group)}\n")

        # Ballchasing's group search only returns top level groups - sub
        # groups are reachable only via ?group=<parent>. So the plain
        # creator=me listing is already exactly the top level, and passing a
        # parent gives its immediate children (not the whole subtree).
        # The creator filter only applies to the top level listing: a group
        # you own can hold sub groups someone else created, and those are
        # still worth seeing here.
        groups = [
            g
            async for g in bc.get_groups(
                name=name,
                creator=None if parent else "me",
                group=parent,
                count=count,
                sort_by=sort_by,
                sort_dir=sort_dir,
                created_after=created_after,
                created_before=created_before,
            )
        ]

        # One extra request per group, so it stays behind a flag.
        subgroup_counts: dict[str, int] = {}
        if show_subgroups:
            for group in groups:
                subgroup_counts[group.id] = len(
                    [c async for c in bc.get_groups(group=group.id, count=200)]
                )

        if as_json:
            print(
                json.dumps(
                    [
                        {
                            "id": g.id,
                            "name": g.name,
                            "link": web_link(g),
                            "api_link": str(g.link),
                            "created": g.created.isoformat(),
                            "direct_replays": g.direct_replays or 0,
                            "indirect_replays": g.indirect_replays or 0,
                            "shared": g.shared,
                            "player_identification": g.player_identification,
                            "team_identification": g.team_identification,
                            **(
                                {"sub_groups": subgroup_counts[g.id]}
                                if show_subgroups
                                else {}
                            ),
                        }
                        for g in groups
                    ],
                    indent=2,
                    default=str,
                )
            )
            return

        if not groups:
            print("No sub groups found." if parent else "No top level groups found.")
            return

        for group in groups:
            print_group(group, subgroup_counts.get(group.id) if show_subgroups else None)
            print()

        replays = sum(g.indirect_replays or 0 for g in groups)
        label = "sub group" if parent else "top level group"
        print(f"{len(groups)} {label}{'' if len(groups) == 1 else 's'}, {replays} replays")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="List the top level replay groups owned by the "
        "authenticated ballchasing account. Sub groups are not shown, unless "
        "a parent group is given - then its immediate children are listed."
    )
    parser.add_argument(
        "parent",
        type=str,
        nargs="?",
        default=None,
        help="Optional parent group id or URL. Lists that group's immediate "
        "sub groups instead of your top level groups",
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Only show groups whose name matches this filter",
    )
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=200,
        help="Maximum number of groups to list (default: 200)",
    )
    parser.add_argument(
        "--sort-by",
        type=GroupSortBy,
        choices=list(GroupSortBy),
        default=GroupSortBy.CREATED,
        help="Field to sort by (default: created)",
    )
    parser.add_argument(
        "--sort-dir",
        type=SortDir,
        choices=list(SortDir),
        default=SortDir.DESCENDING,
        help="Sort direction (default: desc)",
    )
    parser.add_argument(
        "--created-after",
        type=str,
        default=None,
        help="Only include groups created after this RFC3339 date, "
        "e.g. 2025-01-02T15:00:05+01:00",
    )
    parser.add_argument(
        "--created-before",
        type=str,
        default=None,
        help="Only include groups created before this RFC3339 date",
    )
    parser.add_argument(
        "-s",
        "--subgroups",
        action="store_true",
        help="Also count each group's direct sub groups (one request per group)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Dump the listing as JSON instead of formatted text",
    )
    argv = parser.parse_args()

    key = os.getenv("BALLCHASING_KEY")
    if not key:
        raise ValueError("Missing BALLCHASING_KEY in .env file")

    asyncio.run(
        list_groups(
            key,
            parse_group_id(argv.parent) if argv.parent else None,
            argv.name,
            argv.count,
            argv.sort_by,
            argv.sort_dir,
            argv.created_after,
            argv.created_before,
            argv.subgroups,
            argv.json,
        )
    )
