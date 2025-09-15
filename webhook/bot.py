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

from typing import Any, Dict
import asyncio
import json
import logging
import re
from urllib.parse import urlparse

import aiohttp

from maubot import MessageEvent, Plugin
from maubot.handlers import command, event
from mautrix.types import (
    EventID,
    EventType,
    MessageType,
    RoomID,
    StateEvent,
)
from mautrix.util.async_db import UpgradeTable
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

from .db import WebhookDBManager, WebhookRegistration
from .migrations import upgrade_table


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("webhook_timeout")
        helper.copy("max_webhook_retries")
        helper.copy("webhook_user_agent")
        helper.copy("message_data_template")
        helper.copy("custom_fields")
        helper.copy("response_template")
        helper.copy("include_empty_fields")

    @property
    def webhook_timeout(self) -> int:
        return self.get("webhook_timeout", 30)

    @property
    def max_webhook_retries(self) -> int:
        return self.get("max_webhook_retries", 3)

    @property
    def webhook_user_agent(self) -> str:
        return self.get("webhook_user_agent", "Maubot-Webhook-Plugin/1.0")

    @property
    def message_data_template(self) -> Dict[str, str]:
        return self.get("message_data_template", {
            "event_id": "{event_id}",
            "room_id": "{room_id}",
            "sender": "{sender}",
            "timestamp": "{timestamp}",
            "message_type": "{message_type}",
            "body": "{body}",
            "formatted_body": "{formatted_body}",
            "format": "{format}"
        })

    @property
    def custom_fields(self) -> Dict[str, Any]:
        return self.get("custom_fields", {})

    @property
    def response_template(self) -> str:
        return self.get("response_template", "🤖 **Webhook Response:** {response}")

    @property
    def include_empty_fields(self) -> bool:
        return self.get("include_empty_fields", False)


class WebhookBot(Plugin):
    db: WebhookDBManager
    config: Config

    @classmethod
    def get_config_class(cls) -> type[BaseProxyConfig]:
        return Config

    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable:
        return upgrade_table

    async def start(self) -> None:
        await super().start()
        self.config.load_and_update()
        self.db = WebhookDBManager(self.database)

    async def stop(self) -> None:
        await super().stop()

    def is_valid_url(self, url: str) -> bool:
        """Validate if the provided URL is a valid HTTP/HTTPS URL."""
        try:
            parsed = urlparse(url)
            return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
        except Exception:
            return False

    @command.new("webhook", help="Webhook management commands")
    async def webhook_command(self, evt: MessageEvent) -> None:
        await evt.respond("Available webhook commands:\n"
                         "• `!webhook register <url>` - Register a webhook URL\n"
                         "• `!webhook unregister` - Unregister your webhook\n"
                         "• `!webhook list` - List all webhooks in this room\n"
                         "• `!webhook status` - Check your webhook status")

    @webhook_command.subcommand("register", help="Register a webhook URL")
    @command.argument("url", pass_raw=True, required=True)
    async def register_webhook(self, evt: MessageEvent, url: str) -> None:
        """Register a webhook URL for the current room and user."""
        url = url.strip()
        
        if not url:
            await evt.respond("❌ Please provide a webhook URL.\n"
                            "Usage: `!webhook register <url>`")
            return

        if not self.is_valid_url(url):
            await evt.respond("❌ Invalid URL. Please provide a valid HTTP or HTTPS URL.")
            return

        try:
            registration = await self.db.register_webhook(
                room_id=evt.room_id,
                user_id=evt.sender,
                webhook_url=url,
            )
            
            await evt.respond(
                f"✅ Webhook registered successfully!\n"
                f"**URL:** `{url}`\n"
                f"**Room:** {evt.room_id}\n"
                f"**User:** {evt.sender}\n\n"
                f"All messages in this room will now be forwarded to your webhook."
            )
            
            self.log.info(f"Webhook registered: {url} for user {evt.sender} in room {evt.room_id}")
            
        except Exception as e:
            self.log.error(f"Failed to register webhook: {e}")
            await evt.respond(f"❌ Failed to register webhook: {str(e)}")

    @webhook_command.subcommand("unregister", help="Unregister your webhook")
    async def unregister_webhook(self, evt: MessageEvent) -> None:
        """Unregister the webhook for the current room and user."""
        try:
            success = await self.db.unregister_webhook(
                room_id=evt.room_id,
                user_id=evt.sender,
            )
            
            if success:
                await evt.respond("✅ Webhook unregistered successfully.")
                self.log.info(f"Webhook unregistered for user {evt.sender} in room {evt.room_id}")
            else:
                await evt.respond("❌ No webhook found to unregister.")
                
        except Exception as e:
            self.log.error(f"Failed to unregister webhook: {e}")
            await evt.respond(f"❌ Failed to unregister webhook: {str(e)}")

    @webhook_command.subcommand("list", help="List all webhooks in this room")
    async def list_webhooks(self, evt: MessageEvent) -> None:
        """List all webhook registrations in the current room."""
        try:
            webhooks = await self.db.list_webhooks_for_room(evt.room_id)
            
            if not webhooks:
                await evt.respond("No webhooks registered in this room.")
                return

            response = "**Webhooks in this room:**\n\n"
            for webhook in webhooks:
                status = "🟢 Active" if webhook.enabled else "🔴 Disabled"
                response += (
                    f"• **User:** {webhook.user_id}\n"
                    f"  **URL:** `{webhook.webhook_url}`\n"
                    f"  **Status:** {status}\n"
                    f"  **Created:** {webhook.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )
            
            await evt.respond(response)
            
        except Exception as e:
            self.log.error(f"Failed to list webhooks: {e}")
            await evt.respond(f"❌ Failed to list webhooks: {str(e)}")

    @webhook_command.subcommand("status", help="Check your webhook status")
    async def webhook_status(self, evt: MessageEvent) -> None:
        """Check the webhook status for the current user in this room."""
        try:
            webhook = await self.db.get_webhook_by_room_and_user(
                room_id=evt.room_id,
                user_id=evt.sender,
            )
            
            if not webhook:
                await evt.respond("❌ No webhook registered for you in this room.")
                return

            status = "🟢 Active" if webhook.enabled else "🔴 Disabled"
            await evt.respond(
                f"**Your webhook status:**\n"
                f"**URL:** `{webhook.webhook_url}`\n"
                f"**Status:** {status}\n"
                f"**Created:** {webhook.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
        except Exception as e:
            self.log.error(f"Failed to get webhook status: {e}")
            await evt.respond(f"❌ Failed to get webhook status: {str(e)}")

    @event.on(EventType.ROOM_MESSAGE)
    async def on_message(self, evt: MessageEvent) -> None:
        """Forward all messages to registered webhooks."""
        # Don't forward messages from the bot itself
        if evt.sender == self.client.mxid:
            return

        # Don't forward command messages
        if evt.content.msgtype == MessageType.TEXT:
            text = evt.content.body or ""
            if text.strip().startswith("!webhook"):
                return

        try:
            webhooks = await self.db.get_webhooks_by_room(evt.room_id)
            
            if not webhooks:
                return

            # Prepare message data using configurable template
            raw_data = {
                "event_id": str(evt.event_id),
                "room_id": str(evt.room_id),
                "sender": str(evt.sender),
                "timestamp": evt.timestamp,
                "message_type": str(evt.content.msgtype),
                "body": evt.content.body,
                "formatted_body": getattr(evt.content, "formatted_body", None),
                "format": str(getattr(evt.content, "format", None)) if getattr(evt.content, "format", None) else None,
            }

            # Build message data using template
            message_data = {}
            for key, template in self.config.message_data_template.items():
                try:
                    value = template.format(**raw_data)
                    # Only include field if it has content or if include_empty_fields is True
                    if self.config.include_empty_fields or (value and value != "None"):
                        message_data[key] = value
                except (KeyError, ValueError) as e:
                    self.log.warning(f"Failed to format template for key '{key}': {e}")
                    if self.config.include_empty_fields:
                        message_data[key] = None

            # Add custom fields
            message_data.update(self.config.custom_fields)

            # Forward to all webhooks in parallel
            tasks = []
            for webhook in webhooks:
                task = self._forward_to_webhook(webhook, message_data, evt)
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            self.log.error(f"Error in message forwarding: {e}")

    async def _forward_to_webhook(
        self, 
        webhook: WebhookRegistration, 
        message_data: Dict[str, Any],
        original_evt: MessageEvent
    ) -> None:
        """Forward a message to a specific webhook."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.webhook_timeout)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": self.config.webhook_user_agent,
                }
                
                for attempt in range(self.config.max_webhook_retries + 1):
                    try:
                        async with session.post(
                            webhook.webhook_url,
                            json=message_data,
                            headers=headers,
                        ) as response:
                            
                            if response.status == 200:
                                # Check if the webhook returned a response to send back
                                try:
                                    response_text = await response.text()
                                    if response_text and isinstance(response_text, str):
                                        # Send the webhook response back to the chat using template
                                        formatted_response = self.config.response_template.format(response=response_text.strip())
                                        await original_evt.respond(formatted_response)
                                            
                                except (json.JSONDecodeError, KeyError):
                                    # Webhook didn't return JSON or doesn't have a response field
                                    pass
                                
                                self.log.debug(
                                    f"Successfully forwarded message to webhook {webhook.webhook_url}"
                                )
                                return
                            else:
                                self.log.warning(
                                    f"Webhook {webhook.webhook_url} returned status {response.status}"
                                )
                                
                    except asyncio.TimeoutError:
                        self.log.warning(
                            f"Timeout forwarding to webhook {webhook.webhook_url} (attempt {attempt + 1})"
                        )
                    except aiohttp.ClientError as e:
                        self.log.warning(
                            f"Client error forwarding to webhook {webhook.webhook_url}: {e} (attempt {attempt + 1})"
                        )
                    
                    if attempt < self.config.max_webhook_retries:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
                self.log.error(
                    f"Failed to forward message to webhook {webhook.webhook_url} after {self.config.max_webhook_retries + 1} attempts"
                )
                
        except Exception as e:
            self.log.error(f"Unexpected error forwarding to webhook {webhook.webhook_url}: {e}")

    @event.on(EventType.ROOM_TOMBSTONE)
    async def tombstone(self, evt: StateEvent) -> None:
        if not evt.content.replacement_room:
            return
        await self.db.update_room_id(evt.room_id, evt.content.replacement_room)
        self.log.info(f"Updated room ID from {evt.room_id} to {evt.content.replacement_room}")