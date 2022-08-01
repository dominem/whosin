import asyncio
import random

import websockets
import json

uri = 'ws://localhost:8000/ws'
tokens = ['token1', 'token2', 'token3', 'token4']


async def do_random_thing(n, ws):
    while True:
        await asyncio.sleep(random.randint(10, 30))
        im_in = random.choice([True, False])
        log = "I'm in!" if im_in else "I'm out!"
        print(f'[{n}] >>> {log}')
        await ws.send(json.dumps({'im_in': im_in}))


async def add_user(n: int, token: str):
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({'token': token}))
        print(f'[{n}] <<< logged in')
        task = asyncio.Task(do_random_thing(n, ws))
        try:
            while True:
                msg = await ws.recv()
                print(f'[{n}] <<< {msg}')
        except Exception:
            task.cancel()
            raise


async def main():
    tasks = []
    for i in range(1, 500):
        task = asyncio.Task(add_user(i, random.choice(tokens)))
        tasks.append(task)
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())


# With 500 users each sending every 10-30 seconds, the server becomes very busy.
# TODO: don't incr (decr) when already in (out).
