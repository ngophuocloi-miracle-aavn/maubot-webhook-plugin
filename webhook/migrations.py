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


@upgrade_table.register(description="Create webhook registration table with support for multiple webhooks per user", upgrades_to=1)
async def upgrade_latest(conn: Connection, scheme: Scheme) -> None:
    await conn.execute(
        f"""CREATE TABLE IF NOT EXISTS webhook_registration (
            id          SERIAL,
            room_id     TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            enabled     BOOLEAN DEFAULT true,
            created_at  timestamp NOT NULL,
            message_data_template TEXT,

            PRIMARY KEY (id),
            UNIQUE (room_id, user_id, webhook_url)
        )"""
    )