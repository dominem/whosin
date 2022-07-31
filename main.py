import asyncio
import logging.config
from asyncio import IncompleteReadError
from typing import List, Optional, Dict

import aioredis
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from websockets.exceptions import ConnectionClosedError

logger = logging.getLogger('whosin')
logger.setLevel(logging.DEBUG)
logger_handler = logging.StreamHandler()
logger_formatter = logging.Formatter('[%(name)s] [%(levelname)s] %(message)s')
logger_handler.setFormatter(logger_formatter)
logger.addHandler(logger_handler)

app = FastAPI()

templates = Jinja2Templates(directory='templates')


class AuthenticationError(Exception):
    pass


class Authentication:
    def __init__(self):
        self.users = {
            'token1': 'dominik',
            'token2': 'ela',
            'token3': 'wiktor',
            'token4': 'maja',
        }

    def authenticate(self, token: str) -> Optional[str]:
        try:
            return self.users[token]
        except KeyError:
            raise AuthenticationError()


class WebsocketApp:
    def __init__(self, auth: Authentication, logger: logging.Logger, redis: aioredis.Redis):
        self.active_websockets: List[WebSocket] = []
        self.auth = auth
        self.authenticated: Dict[WebSocket, str] = {}
        self.redis = redis
        self.pubsub = self.redis.pubsub()
        self.logger = logger
        self.logger.debug('init')

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_websockets.append(websocket)

    async def authenticate(self, websocket: WebSocket, token: str):
        try:
            user = self.auth.authenticate(token)
            self.authenticated[websocket] = user
            self.logger.debug(f'authenticated {user}')
        except AuthenticationError:
            self.logger.debug(f'authentication failed for {token}')
            raise

    async def disconnect(self, websocket: WebSocket):
        self.active_websockets.remove(websocket)
        if websocket in self.authenticated:
            self.authenticated.pop(websocket)

    async def im_in(self, websocket: WebSocket):
        username = self.authenticated[websocket]
        people_in = await self.redis.incr('whosin:people_in')
        await self.redis.set(f'whosin:{username}:imin', 1)
        await self.redis.publish(f'whosin:{username}:imin', 1)
        await self.redis.publish('whosin:people_in', people_in)

    async def im_out(self, websocket: WebSocket):
        username = self.authenticated[websocket]
        people_in = await self.redis.decr('whosin:people_in')
        await self.redis.set(f'whosin:{username}:imin', 0)
        await self.redis.publish(f'whosin:{username}:imin', 0)
        await self.redis.publish('whosin:people_in', people_in)

    async def send_user_data(self, websocket: WebSocket):
        username = self.authenticated[websocket]
        people_in = int(await self.redis.get('whosin:people_in') or 0)
        im_in = bool(int(await self.redis.get(f'whosin:{username}:imin') or 0))
        await websocket.send_json({
            'people_in': people_in,
            'im_in': im_in,
            'username': username,
        })

    async def broadcast_people_in(self):
        for websocket in self.active_websockets:
            try:
                await self.send_user_data(websocket)
            except (IncompleteReadError, ConnectionClosedError):
                # These exceptions might be raised on the app closure
                # because at the time all websockets are disconnected.
                pass

    async def subscribe_to_changes(self, websocket: WebSocket) -> asyncio.Task:
        username = self.authenticated[websocket]
        pubsub = self.redis.pubsub()
        await pubsub.subscribe('whosin:people_in', f'whosin:{username}:imin')
        return asyncio.create_task(self.listen_to_changes(websocket, pubsub))

    async def listen_to_changes(self, websocket: WebSocket, pubsub: aioredis.client.PubSub):
        username = self.authenticated[websocket]
        self.logger.debug(f'(Reader) Waiting for message for: {username}')
        async for message in pubsub.listen():
            self.logger.debug(f'(Reader) Waiting for message for: {username}')
            if message is not None:
                self.logger.debug(f'(Reader) Message received: {message}')
                self.logger.debug(f'(Reader) Message data: {message["data"]}, type: {type(message["data"])}')
                if message['type'] == 'message':
                    if message['channel'] == 'whosin:people_in':
                        people_in = int(message['data'])
                        await websocket.send_json({'people_in': people_in})
                    elif message['channel'] == f'whosin:{username}:imin':
                        im_in = bool(int(message['data']))
                        await websocket.send_json({'im_in': im_in})


ws_app = WebsocketApp(
    auth=Authentication(),
    logger=logger.getChild('ws'),
    redis=aioredis.from_url('redis://localhost', decode_responses=True),
)


@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


@app.websocket('/ws')
async def ws_index(websocket: WebSocket):
    await ws_app.connect(websocket)
    try:
        auth_data = await websocket.receive_json()
        await ws_app.authenticate(websocket, auth_data.get('token'))
        await ws_app.send_user_data(websocket)
        sub = await ws_app.subscribe_to_changes(websocket)
        try:
            while True:
                logger.debug('waiting for ws message')
                data = await websocket.receive_json()
                if data.get('im_in') is True:
                    await ws_app.im_in(websocket)
                elif data.get('im_in') is False:
                    await ws_app.im_out(websocket)
        except Exception:
            sub.cancel()
            raise
    except WebSocketDisconnect:
        await ws_app.disconnect(websocket)
    except AuthenticationError:
        await ws_app.disconnect(websocket)
        await websocket.close(code=1011, reason='authentication failed')
