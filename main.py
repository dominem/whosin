import logging.config
from asyncio import IncompleteReadError
from typing import List, Optional, Dict, Set

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
    def __init__(self, auth: Authentication, logger: logging.Logger):
        self.active_websockets: List[WebSocket] = []
        self.people_in: Set[str] = set()
        self.auth = auth
        self.authenticated: Dict[WebSocket, str] = {}
        self.logger = logger
        self.logger.debug('init')

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_websockets.append(websocket)

    def authenticate(self, websocket: WebSocket, token: str):
        try:
            user = self.auth.authenticate(token)
            self.authenticated[websocket] = user
            self.logger.debug(f'authenticated {user}')
        except AuthenticationError:
            self.logger.debug(f'authentication failed for {token}')
            raise

    def disconnect(self, websocket: WebSocket):
        self.active_websockets.remove(websocket)
        if websocket in self.authenticated:
            self.authenticated.pop(websocket)

    def im_in(self, websocket: WebSocket):
        self.people_in.add(self.authenticated[websocket])

    def im_out(self, websocket: WebSocket):
        try:
            self.people_in.remove(self.authenticated[websocket])
        except KeyError:
            pass

    async def send_user_data(self, websocket: WebSocket):
        await websocket.send_json({
            'people_in': len(self.people_in),
            'im_in': self.authenticated[websocket] in self.people_in
        })

    async def broadcast_people_in(self):
        for websocket in self.active_websockets:
            try:
                await websocket.send_json({
                    'people_in': len(self.people_in),
                    'im_in': self.authenticated[websocket] in self.people_in,
                })
            except (IncompleteReadError, ConnectionClosedError):
                # These exceptions might be raised on the app closure
                # because at the time all websockets are disconnected.
                pass


ws_app = WebsocketApp(
    auth=Authentication(),
    logger=logger.getChild('ws'),
)


@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


@app.websocket('/ws')
async def ws_index(websocket: WebSocket):
    await ws_app.connect(websocket)
    try:
        auth_data = await websocket.receive_json()
        ws_app.authenticate(websocket, auth_data.get('token'))
        await ws_app.send_user_data(websocket)
        while True:
            data = await websocket.receive_json()
            if data.get('im_in') is True:
                ws_app.im_in(websocket)
                await ws_app.broadcast_people_in()
            elif data.get('im_in') is False:
                ws_app.im_out(websocket)
                await ws_app.broadcast_people_in()
    except WebSocketDisconnect:
        ws_app.disconnect(websocket)
        await ws_app.broadcast_people_in()
    except AuthenticationError:
        ws_app.disconnect(websocket)
        await websocket.close(code=1011, reason='authentication failed')
        await ws_app.broadcast_people_in()
