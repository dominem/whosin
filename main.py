from asyncio import IncompleteReadError
from typing import List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from websockets.exceptions import ConnectionClosedError

app = FastAPI()

templates = Jinja2Templates(directory='templates')


class WebsocketApp:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.people_in: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        if websocket in self.people_in:
            self.people_in.remove(websocket)

    def im_in(self, websocket: WebSocket):
        if websocket not in self.people_in:
            self.people_in.append(websocket)

    def im_out(self, websocket: WebSocket):
        if websocket in self.people_in:
            self.people_in.remove(websocket)

    async def send_people_in(self, websocket: WebSocket):
        await websocket.send_json({'people_in': len(self.people_in)})

    async def broadcast_people_in(self):
        for connection in self.active_connections:
            try:
                await connection.send_json({'people_in': len(self.people_in)})
            except (IncompleteReadError, ConnectionClosedError):
                # These exceptions might be raised on the app closure
                # because at the time all websockets are disconnected.
                pass


ws_app = WebsocketApp()


@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


@app.websocket('/ws')
async def ws_index(websocket: WebSocket):
    await ws_app.connect(websocket)
    try:
        await ws_app.send_people_in(websocket)
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
