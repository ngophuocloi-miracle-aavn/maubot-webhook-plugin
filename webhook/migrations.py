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
from mautrix.util.async_db import Connection, Scheme, UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Create webhook registration table", upgrades_to=1)
async def upgrade_latest(conn: Connection, scheme: Scheme) -> None:
    gen = "GENERATED ALWAYS AS IDENTITY" if scheme != Scheme.SQLITE else ""
    await conn.execute(
        f"""CREATE TABLE IF NOT EXISTS webhook_registration (
            id          INTEGER {gen},
            room_id     TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            enabled     BOOLEAN DEFAULT true,
            created_at  timestamp NOT NULL,

            PRIMARY KEY (id),
            UNIQUE (room_id, user_id)
        )"""
    )


@upgrade_table.register(description="Remove unique constraint on (room_id, user_id) to allow multiple webhooks per user", upgrades_to=3)
async def upgrade_v3(conn: Connection, scheme: Scheme) -> None:
    if scheme == Scheme.SQLITE:
        # SQLite doesn't support dropping constraints, so we need to recreate the table
        await conn.execute("""
            CREATE TABLE webhook_registration_new (
                id          INTEGER PRIMARY KEY,
                room_id     TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                webhook_url TEXT NOT NULL,
                enabled     BOOLEAN DEFAULT true,
                created_at  timestamp NOT NULL,
                message_data_template TEXT,
                
                UNIQUE (room_id, user_id, webhook_url)
            )
        """)
        
        # Copy data from old table to new table
        await conn.execute("""
            INSERT INTO webhook_registration_new (id, room_id, user_id, webhook_url, enabled, created_at, message_data_template)
            SELECT id, room_id, user_id, webhook_url, enabled, created_at, message_data_template
            FROM webhook_registration
        """)
        
        # Drop old table and rename new table
        await conn.execute("DROP TABLE webhook_registration")
        await conn.execute("ALTER TABLE webhook_registration_new RENAME TO webhook_registration")
    else:
        # PostgreSQL - drop the old constraint and add new one
        await conn.execute("ALTER TABLE webhook_registration DROP CONSTRAINT webhook_registration_room_id_user_id_key")
        await conn.execute("ALTER TABLE webhook_registration ADD CONSTRAINT webhook_registration_room_user_url_key UNIQUE (room_id, user_id, webhook_url)")