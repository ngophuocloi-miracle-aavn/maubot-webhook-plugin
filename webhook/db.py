# webhook-plugin - A maubot plugin to register and forward messages to webhooks.
# Copyright (C) 2025
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from asyncpg import Record
from attr import dataclass
import attr

from mautrix.types import RoomID, UserID
from mautrix.util.async_db import Database, Scheme

# TODO make this import unconditional after updating mautrix-python
try:
    from mautrix.util.async_db import SQLiteCursor
except ImportError:
    SQLiteCursor = None


@dataclass
class WebhookRegistration:
    id: int
    room_id: RoomID
    user_id: UserID
    webhook_url: str
    enabled: bool = True
    created_at: datetime = attr.ib(factory=datetime.now)

    @classmethod
    def from_row(cls, row: Record | None) -> WebhookRegistration | None:
        if not row:
            return None
        
        created_at = row["created_at"]
        if not isinstance(created_at, datetime):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.now()
        
        return cls(
            id=row["id"],
            room_id=row["room_id"],
            user_id=row["user_id"],
            webhook_url=row["webhook_url"],
            enabled=bool(row["enabled"]),
            created_at=created_at,
        )


class WebhookDBManager:
    db: Database

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_webhooks_by_room(self, room_id: RoomID) -> list[WebhookRegistration]:
        """Get all active webhook registrations for a room."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at
        FROM webhook_registration 
        WHERE room_id = $1 AND enabled = true
        """
        rows = await self.db.fetch(q, room_id)
        return [WebhookRegistration.from_row(row) for row in rows if row]

    async def get_webhook_by_room_and_user(self, room_id: RoomID, user_id: UserID) -> WebhookRegistration | None:
        """Get webhook registration for a specific room and user."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at
        FROM webhook_registration 
        WHERE room_id = $1 AND user_id = $2
        """
        row = await self.db.fetchrow(q, room_id, user_id)
        return WebhookRegistration.from_row(row)

    async def register_webhook(
        self,
        room_id: RoomID,
        user_id: UserID,
        webhook_url: str,
    ) -> WebhookRegistration:
        """Register a new webhook or update existing one."""
        existing = await self.get_webhook_by_room_and_user(room_id, user_id)
        
        if existing:
            # Update existing webhook
            q = """
            UPDATE webhook_registration 
            SET webhook_url = $3, enabled = true
            WHERE room_id = $1 AND user_id = $2
            RETURNING id, room_id, user_id, webhook_url, enabled, created_at
            """
            row = await self.db.fetchrow(q, room_id, user_id, webhook_url)
            return WebhookRegistration.from_row(row)
        else:
            # Create new webhook registration
            q = """
            INSERT INTO webhook_registration (room_id, user_id, webhook_url, enabled, created_at)
            VALUES ($1, $2, $3, true, $4)
            RETURNING id, room_id, user_id, webhook_url, enabled, created_at
            """
            created_at = datetime.now()
            
            # Handle SQLite differently since it may not support RETURNING
            if self.db.scheme == Scheme.SQLITE:
                insert_q = """
                INSERT INTO webhook_registration (room_id, user_id, webhook_url, enabled, created_at)
                VALUES ($1, $2, $3, true, $4)
                """
                cur = await self.db.execute(insert_q, room_id, user_id, webhook_url, created_at)
                
                if SQLiteCursor is not None:
                    assert isinstance(cur, SQLiteCursor)
                webhook_id = cur.lastrowid
                
                return WebhookRegistration(
                    id=webhook_id,
                    room_id=room_id,
                    user_id=user_id,
                    webhook_url=webhook_url,
                    enabled=True,
                    created_at=created_at,
                )
            else:
                row = await self.db.fetchrow(q, room_id, user_id, webhook_url, created_at)
                return WebhookRegistration.from_row(row)

    async def unregister_webhook(self, room_id: RoomID, user_id: UserID) -> bool:
        """Disable a webhook registration."""
        q = """
        UPDATE webhook_registration 
        SET enabled = false
        WHERE room_id = $1 AND user_id = $2
        """
        result = await self.db.execute(q, room_id, user_id)
        return result != "UPDATE 0"

    async def list_webhooks_for_room(self, room_id: RoomID) -> list[WebhookRegistration]:
        """List all webhook registrations (enabled and disabled) for a room."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at
        FROM webhook_registration 
        WHERE room_id = $1
        ORDER BY created_at DESC
        """
        rows = await self.db.fetch(q, room_id)
        return [WebhookRegistration.from_row(row) for row in rows if row]

    async def update_room_id(self, old: RoomID, new: RoomID) -> None:
        """Update room ID when a room is upgraded."""
        await self.db.execute(
            "UPDATE webhook_registration SET room_id = $1 WHERE room_id = $2", 
            new, old
        )