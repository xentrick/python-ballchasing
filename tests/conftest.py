import pytest
import os
import ballchasing
import asyncio

@pytest.fixture()
async def apikey():
    yield os.environ.get('BALLCHASING_KEY')

@pytest.fixture()
async def bapi(apikey):
    # Ballchasing API object fixture
    async with ballchasing.Api(auth_key=apikey) as bc:
        yield bc




