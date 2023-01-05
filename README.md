# Python Ballchasing
Python wrapper for the ballchasing.com API. 

Note that project is still early in development and is subject to change.

# Import change notes

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

`upload_replay()` has been updated to handle multiple replay files. Accepts a single string or a list of strings containing the path to a replay file.

```
result = await bapi.upload_replay('test.replay')

result = await bapi.upload_replay(['test.replay', 'greatgame.replay'])
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
