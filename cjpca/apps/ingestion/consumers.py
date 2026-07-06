import json
from channels.generic.websocket import AsyncWebsocketConsumer


class IngestionConsumer(AsyncWebsocketConsumer):
    """
    WS /ws/ingestion/<job_id>/

    Streams real-time ingestion log entries to the client.
    Sends JSON messages with shape:
        { stage, message, timestamp, progress_pct, current_stage }
    """

    async def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.group_name = f'ingestion_{self.job_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def ingestion_update(self, event):
        """Relay group messages to the WebSocket client."""
        await self.send(text_data=json.dumps(event['data']))
