# Python Ballchasing (Async)

Python wrapper for the ballchasing.com API. 

This project was forked from https://github.com/Rolv-Arild/python-ballchasing and modified to be asynchronous. All credit goes to Rolv-Alrid, I simply modified how it's used.

# Import change notes

## Ping and Patreon Level

Since we can't call ping to update the Patreon level used for rate limiting in `__ini__` it has to be called manually. I'm not actually sure if this can be accomplished in another way and open to suggestions.

For now it is recommend that you manually specify the limit for your API key level or ping manually.

```
bapi = ballchasing.Api(..., sleep_time_on_rate_limit=3)

bapi = ballchasing.Api(...)
await bapi.ping()
```
## AsyncIterators

Querying multiple replays will result in an `AsyncIterator`. To handle this you can iterate the data like so.

```
result = await bapi.get_replays(...)

async for r in result:
    print(r)
```

Gather `AsyncIterator` into a `List`:

```
async def gather(result):
    # Gather async iterator into list and return
    final = []
    async for r in result: final.append(r)
    return final

result = bapi.get_replays(...)

result_list = await gather(result)
```


# API
The API is exposed via the `ballchasing.Api` class.

Simple example:
```python
import ballchasing
api = ballchasing.Api("Your token here")

# Get a specific replay
replay = api.get_replay("2627e02a-aa46-4e13-b66b-b76a32069a07")
```
