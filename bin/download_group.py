#!/usr/bin/env python3

import argparse
import ballchasing
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

async def download_group(key: str, group_id: str, dest: str):
    bc = ballchasing.Api(auth_key=key, timeout=30)
    print(f"Destination folder: {dest}")
    print(f"Downloading group: {group_id}")
    await bc.download_group(group_id, dest, recursive=True)
    print("Finished downloading replays")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='The Description')
    parser.add_argument(
        'group_id', type=str, 
        help='Ballchasing Group ID')
    parser.add_argument(
        'dest', type=str, help='Destination folder for download')
    argv = parser.parse_args()

    key = os.getenv('BALLCHASING_KEY') 
    if not key:
        raise ValueError('Missing BALLCHASING_API_KEY in .env file')

    dest = Path(argv.dest)
    if not dest.exists():
        raise ValueError('Destination folder does not exist')


    asyncio.run(download_group(key, argv.group_id, argv.dest))

    