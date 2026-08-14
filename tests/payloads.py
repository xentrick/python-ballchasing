"""Minimal response bodies that satisfy the pydantic models in ballchasing.models.

Only required fields are populated; tests override what they care about.
"""

from typing import Any


def uploader_payload(steam_id=76561197960409023, name="tester"):
    return {
        "avatar": "https://example.invalid/avatar.jpg",
        "name": name,
        "profile_url": "https://example.invalid/profile",
        "steam_id": steam_id,
    }


def replay_payload(replay_id="replay-1", **overrides):
    payload = {
        "created": "2024-01-02T03:04:05Z",
        "id": replay_id,
        "link": f"https://example.invalid/replay/{replay_id}",
        "uploader": uploader_payload(),
    }
    payload.update(overrides)
    return payload


def replay_search_payload(ids, next_url=None, count=None):
    payload: dict[str, Any] = {"list": [replay_payload(i) for i in ids]}
    if next_url is not None:
        payload["next"] = next_url
    if count is not None:
        payload["count"] = count
    return payload


def group_payload(group_id="group-1", name="test-group", **overrides):
    payload = {
        "created": "2024-01-02T03:04:05Z",
        "id": group_id,
        "link": f"https://example.invalid/group/{group_id}",
        "name": name,
        "player_identification": "by-id",
        "shared": False,
        "team_identification": "by-player-clusters",
    }
    payload.update(overrides)
    return payload


def group_search_payload(ids, next_url=None):
    payload: dict[str, Any] = {"list": [group_payload(i) for i in ids]}
    if next_url is not None:
        payload["next"] = next_url
    return payload


def ping_payload(name="tester", steam_id="76561197960409023", patreon_type="regular"):
    return {
        "ball": "default",
        "boost": "default",
        "chaser": True,
        "chat": {"hello": "world"},
        "name": name,
        "steam_id": steam_id,
        "type": patreon_type,
    }
