import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class OrderConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        
        self.store_id = self.scope['url_route']['kwargs'].get('store_id')
        self.order_id = self.scope['url_route']['kwargs'].get('order_id')
        
        # If specific order tracking, require auth or check session (optional strictness)
        if self.order_id:
            if not user or not user.is_authenticated:
                await self.close(code=4001)
                return
            self.room_group_name = f'order_{self.order_id}'
        elif self.store_id:
            # PUBLIC TV ACCESS: Allow store channels without login
            self.room_group_name = f'store_{self.store_id}_orders'
        else:
            # PUBLIC GLOBAL ACCESS: Allow global updates without login
            self.room_group_name = 'global_orders'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from room group
    async def order_update(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'order_update',
            'message': message
        }))