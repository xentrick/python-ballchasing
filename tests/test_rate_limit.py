#!/usr/bin/env python3
import os
import logging
import asyncio
import sys
from ballchasing import Api, PatreonType

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


API_KEY = os.environ.get("RSC_BALLCHASING_KEY")
log.debug(f"Ballchasing API Key: {API_KEY}")


async def test_rate_limiter(bapi: Api, task_num: int):
    log.debug(f"[{task_num}] Starting task {task_num}")
    resp = await bapi.get_group("fromunda-frauds-vs-kawaii-bpx13059jy")
    log.debug(f"[{task_num}] Task {task_num} finished")
    return resp


async def main(count: int):
    bapi = await Api.create(auth_key=API_KEY)

    result = await asyncio.gather(
        *(test_rate_limiter(bapi, m) for m in range(0, count))
    )
    log.debug(f"All tasks completed. Total Results: {len(result)}")
    await bapi.close()
    log.debug(f"Total Requests Made: {bapi.total_requests}")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(count))
