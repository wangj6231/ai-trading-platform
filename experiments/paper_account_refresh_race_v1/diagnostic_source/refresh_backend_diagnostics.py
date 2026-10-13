"""Bounded test-only ASGI timing; synthetic balance labels, no auth headers."""
import json
from pathlib import Path
import re
from time import time


class RefreshDiagnostics:
    def __init__(self, application, directory):
        self.application = application
        self.path = Path(directory) / 'backend.jsonl'
        self.count = 0

    def emit(self, kind, identity, **values):
        if self.count >= 256 or not re.fullmatch(r'race-\d{1,4}', identity):
            return
        self.count += 1
        with self.path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps({'kind': kind, 'id': identity, 'at': int(time()*1000), **values})+'\n')

    async def __call__(self, scope, receive, send):
        identity = dict(scope.get('headers', [])).get(b'x-correlation-id', b'').decode('ascii', errors='ignore')
        self.emit('backend-start', identity)

        async def traced_send(message):
            if message['type'] == 'http.response.start':
                self.emit('backend-response', identity, status=message['status'])
            if message['type'] == 'http.response.body' and not message.get('more_body'):
                self.emit('backend-end', identity)
            await send(message)

        async def traced_receive():
            message = await receive()
            if message['type'] == 'http.disconnect':
                self.emit('backend-disconnect', identity)
            return message

        await self.application(scope, traced_receive, traced_send)
