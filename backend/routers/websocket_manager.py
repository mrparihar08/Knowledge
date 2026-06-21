from typing import List, Dict, Optional, Any
from fastapi import WebSocket

class ConnectionManager:
    """
    Manages active WebSocket connections with role-based routing.
    Supports personal messaging and filtered broadcasts (e.g., Security only).
    """
    def __init__(self):
        # List of active connection records: {"ws": WebSocket, "user_id": int, "role": str}
        self.active_connections: List[Dict[str, Any]] = []

    async def connect(self, user_id: int, role: str, websocket: WebSocket):
        """Registers a new connection with user metadata."""
        self.active_connections.append({
            "ws": websocket,
            "user_id": user_id,
            "role": role
        })
        print(f"WS CONNECT: User {user_id} joined as {role}. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Removes a specific connection instance."""
        self.active_connections = [
            conn for conn in self.active_connections if conn["ws"] != websocket
        ]
        print(f"WS DISCONNECT: Connection closed. Remaining: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, user_id: int):
        """Delivers a message to all active sessions of a specific user."""
        for conn in self.active_connections:
            if conn["user_id"] == user_id:
                await conn["ws"].send_json(message)

    async def send_to_multiple_users(self, message: dict, user_ids: List[int]):
        """Delivers a message to all active sessions of a specific set of users."""
        target_ids = set(user_ids)
        for conn in self.active_connections:
            if conn["user_id"] in target_ids:
                await conn["ws"].send_json(message)

    async def broadcast(self, message: dict, role_filter: Optional[List[str]] = None, **kwargs):
        """
        Broadcasts a message to connected clients.
        If role_filter is provided, only users with matching roles receive it.
        """
        for conn in self.active_connections:
            should_send = False
            if role_filter is None:
                should_send = True
            elif conn["role"] in role_filter:
                should_send = True

            if should_send:
                try:
                    await conn["ws"].send_json(message)
                except Exception:
                    # Gracefully handle stale connections that haven't triggered disconnect yet
                    pass

manager = ConnectionManager()