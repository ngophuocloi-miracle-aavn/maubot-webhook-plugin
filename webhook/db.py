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
from typing import Dict, Any, Optional
import json

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
    message_data_template: Optional[Dict[str, str]] = None

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
        
        # Parse message_data_template from JSON if it exists
        message_data_template = None
        if row.get("message_data_template"):
            try:
                message_data_template = json.loads(row["message_data_template"])
            except (json.JSONDecodeError, TypeError):
                pass  # Use None if parsing fails
        
        return cls(
            id=row["id"],
            room_id=row["room_id"],
            user_id=row["user_id"],
            webhook_url=row["webhook_url"],
            enabled=bool(row["enabled"]),
            created_at=created_at,
            message_data_template=message_data_template,
        )


class WebhookDBManager:
    db: Database

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_webhooks_by_room(self, room_id: RoomID) -> list[WebhookRegistration]:
        """Get all active webhook registrations for a room."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
        FROM webhook_registration 
        WHERE room_id = $1 AND enabled = true
        """
        rows = await self.db.fetch(q, room_id)
        return [WebhookRegistration.from_row(row) for row in rows if row]

    async def get_webhook_by_room_and_user(self, room_id: RoomID, user_id: UserID) -> list[WebhookRegistration]:
        """Get all webhook registrations for a specific room and user."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
        FROM webhook_registration 
        WHERE room_id = $1 AND user_id = $2
        ORDER BY created_at DESC
        """
        rows = await self.db.fetch(q, room_id, user_id)
        return [WebhookRegistration.from_row(row) for row in rows if row]

    async def get_webhook_by_id(self, webhook_id: int) -> WebhookRegistration | None:
        """Get a specific webhook by ID."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
        FROM webhook_registration 
        WHERE id = $1
        """
        row = await self.db.fetchrow(q, webhook_id)
        return WebhookRegistration.from_row(row)

    async def register_webhook(
        self,
        room_id: RoomID,
        user_id: UserID,
        webhook_url: str,
        message_data_template: Optional[Dict[str, str]] = None,
        webhook_id: Optional[int] = None,
    ) -> WebhookRegistration:
        """Register a new webhook or enable an existing one by ID."""
        # Convert template to JSON string for storage
        template_json = json.dumps(message_data_template) if message_data_template else None
        
        if webhook_id:
            # Enable existing webhook by ID
            update_q = """
            UPDATE webhook_registration 
            SET enabled = true, message_data_template = $3
            WHERE id = $1 AND user_id = $2
            RETURNING id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
            """
            row = await self.db.fetchrow(update_q, webhook_id, user_id, template_json)
            return WebhookRegistration.from_row(row)
        
        # Check if this exact URL already exists for this user in this room
        existing_q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
        FROM webhook_registration 
        WHERE room_id = $1 AND user_id = $2 AND webhook_url = $3
        """
        existing_row = await self.db.fetchrow(existing_q, room_id, user_id, webhook_url)
        
        if existing_row:
            # Update existing webhook (enable it and update template)
            update_q = """
            UPDATE webhook_registration 
            SET enabled = true, message_data_template = $4
            WHERE room_id = $1 AND user_id = $2 AND webhook_url = $3
            RETURNING id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
            """
            row = await self.db.fetchrow(update_q, room_id, user_id, webhook_url, template_json)
            return WebhookRegistration.from_row(row)
        else:
            # Create new webhook registration
            insert_q = """
            INSERT INTO webhook_registration (room_id, user_id, webhook_url, enabled, created_at, message_data_template)
            VALUES ($1, $2, $3, true, $4, $5)
            RETURNING id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
            """
            created_at = datetime.now()
            
            # Handle SQLite differently since it may not support RETURNING
            if self.db.scheme == Scheme.SQLITE:
                sqlite_insert_q = """
                INSERT INTO webhook_registration (room_id, user_id, webhook_url, enabled, created_at, message_data_template)
                VALUES ($1, $2, $3, true, $4, $5)
                """
                cur = await self.db.execute(sqlite_insert_q, room_id, user_id, webhook_url, created_at, template_json)
                
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
                    message_data_template=message_data_template,
                )
            else:
                row = await self.db.fetchrow(insert_q, room_id, user_id, webhook_url, created_at, template_json)
                return WebhookRegistration.from_row(row)

    async def unregister_webhook(self, room_id: RoomID, user_id: UserID, webhook_url: str = None) -> bool:
        """Disable a specific webhook registration, or all webhooks for a user if webhook_url is None."""
        if webhook_url:
            q = """
            UPDATE webhook_registration 
            SET enabled = false
            WHERE room_id = $1 AND user_id = $2 AND webhook_url = $3
            """
            result = await self.db.execute(q, room_id, user_id, webhook_url)
        else:
            q = """
            UPDATE webhook_registration 
            SET enabled = false
            WHERE room_id = $1 AND user_id = $2
            """
            result = await self.db.execute(q, room_id, user_id)
        
        return result != "UPDATE 0"

    async def unregister_webhook_by_id(self, webhook_id: int, user_id: UserID) -> bool:
        """Disable a webhook registration by ID, but only if it belongs to the user."""
        q = """
        UPDATE webhook_registration 
        SET enabled = false
        WHERE id = $1 AND user_id = $2
        """
        result = await self.db.execute(q, webhook_id, user_id)
        return result != "UPDATE 0"

    async def list_webhooks_for_room(self, room_id: RoomID) -> list[WebhookRegistration]:
        """List all webhook registrations (enabled and disabled) for a room."""
        q = """
        SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
        FROM webhook_registration 
        WHERE room_id = $1
        ORDER BY id ASC
        """
        rows = await self.db.fetch(q, room_id)
        return [WebhookRegistration.from_row(row) for row in rows if row]

    async def update_room_id(self, old: RoomID, new: RoomID) -> None:
        """Update room ID when a room is upgraded."""
        await self.db.execute(
            "UPDATE webhook_registration SET room_id = $1 WHERE room_id = $2", 
            new, old
        )

    async def update_message_template(
        self,
        webhook_id: int,
        user_id: UserID,
        message_data_template: Optional[Dict[str, str]],
    ) -> bool:
        """Update the message data template for a specific webhook."""
        template_json = json.dumps(message_data_template) if message_data_template else None
        
        q = """
        UPDATE webhook_registration 
        SET message_data_template = $3
        WHERE id = $1 AND user_id = $2
        """
        result = await self.db.execute(q, webhook_id, user_id, template_json)
        return result != "UPDATE 0"

    async def delete_webhook(
        self,
        room_id: RoomID,
        user_id: UserID,
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Delete webhook(s) from the database."""
        if webhook_url:
            # Delete specific webhook by URL
            q = """
            DELETE FROM webhook_registration 
            WHERE room_id = $1 AND user_id = $2 AND webhook_url = $3
            """
            result = await self.db.execute(q, room_id, user_id, webhook_url)
        else:
            # Delete all webhooks for user in room
            q = """
            DELETE FROM webhook_registration 
            WHERE room_id = $1 AND user_id = $2
            """
            result = await self.db.execute(q, room_id, user_id)
        
        return result != "DELETE 0"

    async def delete_webhook_by_id(
        self,
        webhook_id: int,
        user_id: UserID,
    ) -> bool:
        """Delete a specific webhook by ID (with user verification)."""
        q = """
        DELETE FROM webhook_registration 
        WHERE id = $1 AND user_id = $2
        """
        result = await self.db.execute(q, webhook_id, user_id)
        return result != "DELETE 0"