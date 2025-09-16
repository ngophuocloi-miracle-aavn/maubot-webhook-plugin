# webhook-plugin - A maubot plugin to register and forward messages to webhooks.
# Copyright (C) 2025
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
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
    Format,
    MessageType,
    RoomID,
    StateEvent,
    TextMessageEventContent,
)
from mautrix.util.async_db import UpgradeTable
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.util.formatter import EntityType, MarkdownString, MatrixParser
from mautrix.util import markdown

from .db import WebhookDBManager, WebhookRegistration
from .migrations import upgrade_table


class HumanReadableString(MarkdownString):
    def format(self, entity_type: EntityType, **kwargs) -> MarkdownString:
        if entity_type == EntityType.URL and kwargs["url"] != self.text:
            self.text = f"{self.text} ({kwargs['url']})"
            return self
        return super(HumanReadableString, self).format(entity_type, **kwargs)

class MaubotHTMLParser(MatrixParser[HumanReadableString]):
    fs = HumanReadableString


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
    
    async def _parse_formatted(
        self, message: str, allow_html: bool = True, render_markdown: bool = True
    ) -> tuple[str, str]:
        if render_markdown:
            html_content = markdown.render(message, allow_html=allow_html)
        elif allow_html:
            html_content = message
        else:
            return message, html.escape(message)
        text = (await MaubotHTMLParser().parse(html_content)).text
        if len(text) > 100 and len(text) + len(html_content) > 40000:
            text = text[:100] + "[long message cut off]"
        return text, html_content

    async def _send_text_reply(self, reply_to: MessageEvent, message: str, allow_html: bool = True, render_markdown: bool = True) -> EventID:
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=message)
        content.set_reply(reply_to)
        if render_markdown or allow_html:
            content.format = Format.HTML
            content.body, content.formatted_body = await self._parse_formatted(message, allow_html=allow_html, render_markdown=render_markdown)
        try:
            return await self.client.send_message_event(reply_to.room_id, EventType.ROOM_MESSAGE, content)
        except Exception as e:
            self.log.warning(f"Failed to send reply to {reply_to.event_id} in {reply_to.room_id}: {e}")

    def is_valid_url(self, url: str) -> bool:
        """Validate if the provided URL is a valid HTTP/HTTPS URL."""
        try:
            parsed = urlparse(url)
            return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
        except Exception:
            return False

    @command.new("webhook", help="Webhook management commands")
    async def webhook_command(self, evt: MessageEvent) -> None:
        await self._send_text_reply(evt, "Available webhook commands:\n"
                         "• `!webhook register <url>` - Register a new webhook URL\n"
                         "• `!webhook unregister [url|id]` - Delete webhook(s)\n"
                         "• `!webhook disable <id>` - Disable a webhook\n"
                         "• `!webhook enable <id>` - Enable a webhook\n"
                         "• `!webhook list` - List all webhooks in this room\n"
                         "• `!webhook configure <id> <template>` - Configure message template for a webhook\n"
                         "• `!webhook template <id>` - Show webhook template\n"
                         "• `!webhook reset-template <id>` - Reset webhook template")

    @webhook_command.subcommand("register", help="Register a webhook URL")
    @command.argument("url", pass_raw=True, required=True)
    async def register_webhook(self, evt: MessageEvent, url: str) -> None:
        """Register a webhook URL for the current room and user."""
        url = url.strip()
        
        if not url:
            await self._send_text_reply(evt, "❌ Please provide a webhook URL.\n"
                            "Usage: `!webhook register <url>`")
            return

        if not self.is_valid_url(url):
            await self._send_text_reply(evt, "❌ Invalid URL. Please provide a valid HTTP or HTTPS URL.")
            return

        try:
            registration = await self.db.register_webhook(
                room_id=evt.room_id,
                user_id=evt.sender,
                webhook_url=url,
            )
            
            await self._send_text_reply(evt,
                f"✅ Webhook registered successfully!\n"
                f"* **URL:** `{url}`\n"
                f"* **Room:** {evt.room_id}\n"
                f"* **User:** {evt.sender}\n\n"
                f"All messages in this room will now be forwarded to your webhook."
            )
            
            self.log.info(f"Webhook registered: {url} for user {evt.sender} in room {evt.room_id}")
            
        except Exception as e:
            self.log.error(f"Failed to register webhook: {e}")
            await self._send_text_reply(evt, f"❌ Failed to register webhook: {str(e)}")

    @webhook_command.subcommand("unregister", help="Delete your webhooks")
    @command.argument("target", pass_raw=True, required=False)
    async def unregister_webhook(self, evt: MessageEvent, target: str = "") -> None:
        """Delete webhook(s) for the current room and user."""
        target = target.strip()
        
        try:
            # Get user's webhooks first
            user_webhooks = await self.db.get_webhook_by_room_and_user(evt.room_id, evt.sender)
            
            if not user_webhooks:
                await self._send_text_reply(evt, "❌ No webhooks found to delete.")
                return
            
            if not target:
                # Delete all webhooks for this user
                success = await self.db.delete_webhook(
                    room_id=evt.room_id,
                    user_id=evt.sender,
                )
                
                if success:
                    count = len(user_webhooks)
                    await self._send_text_reply(evt, f"✅ {count} webhook{'s' if count != 1 else ''} deleted successfully.")
                    self.log.info(f"All webhooks deleted for user {evt.sender} in room {evt.room_id}")
                else:
                    await self._send_text_reply(evt, "❌ Failed to delete webhooks.")
            
            elif target.isdigit():
                # Delete by webhook ID
                webhook_id = int(target)
                webhook = next((w for w in user_webhooks if w.id == webhook_id), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No webhook found with ID {webhook_id}.")
                    return
                
                success = await self.db.delete_webhook_by_id(webhook_id, evt.sender)
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook ID {webhook_id} deleted successfully.")
                    self.log.info(f"Webhook ID {webhook_id} deleted for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to delete webhook ID {webhook_id}.")
            
            else:
                # Delete by URL
                webhook = next((w for w in user_webhooks if w.webhook_url == target), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No webhook found with URL: {target}")
                    return
                
                success = await self.db.delete_webhook(
                    room_id=evt.room_id,
                    user_id=evt.sender,
                    webhook_url=target,
                )
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook deleted successfully: {target}")
                    self.log.info(f"Webhook URL {target} deleted for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to delete webhook: {target}")
                
        except Exception as e:
            self.log.error(f"Failed to delete webhook: {e}")
            await self._send_text_reply(evt, f"❌ Failed to delete webhook: {str(e)}")

    @webhook_command.subcommand("disable", help="Disable your webhooks")
    @command.argument("target", pass_raw=True, required=False)
    async def disable_webhook(self, evt: MessageEvent, target: str = "") -> None:
        """Disable webhook(s) for the current room and user."""
        target = target.strip()
        
        try:
            # Get user's webhooks first
            user_webhooks = await self.db.get_webhook_by_room_and_user(evt.room_id, evt.sender)
            active_webhooks = [w for w in user_webhooks if w.enabled]
            
            if not active_webhooks:
                await self._send_text_reply(evt, "❌ No active webhooks found to disable.")
                return
            
            if not target:
                # Disable all webhooks for this user
                success = await self.db.unregister_webhook(
                    room_id=evt.room_id,
                    user_id=evt.sender,
                )
                
                if success:
                    count = len(active_webhooks)
                    await self._send_text_reply(evt, f"✅ {count} webhook{'s' if count != 1 else ''} disabled successfully.")
                    self.log.info(f"All webhooks disabled for user {evt.sender} in room {evt.room_id}")
                else:
                    await self._send_text_reply(evt, "❌ Failed to disable webhooks.")
            
            elif target.isdigit():
                # Disable by webhook ID
                webhook_id = int(target)
                webhook = next((w for w in active_webhooks if w.id == webhook_id), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No active webhook found with ID {webhook_id}.")
                    return
                
                success = await self.db.unregister_webhook_by_id(webhook_id, evt.sender)
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook ID {webhook_id} disabled successfully.")
                    self.log.info(f"Webhook ID {webhook_id} disabled for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to disable webhook ID {webhook_id}.")
            
            else:
                # Disable by URL
                webhook = next((w for w in active_webhooks if w.webhook_url == target), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No active webhook found with URL: {target}")
                    return
                
                success = await self.db.unregister_webhook(
                    room_id=evt.room_id,
                    user_id=evt.sender,
                    webhook_url=target,
                )
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook disabled successfully: {target}")
                    self.log.info(f"Webhook URL {target} disabled for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to disable webhook: {target}")
                
        except Exception as e:
            self.log.error(f"Failed to disable webhook: {e}")
            await self._send_text_reply(evt, f"❌ Failed to disable webhook: {str(e)}")

    @webhook_command.subcommand("enable", help="Enable your disabled webhooks")
    @command.argument("target", pass_raw=True, required=False)
    async def enable_webhook(self, evt: MessageEvent, target: str = "") -> None:
        """Enable disabled webhook(s) for the current room and user."""
        target = target.strip()
        
        try:
            # Get user's webhooks first
            user_webhooks = await self.db.get_webhook_by_room_and_user(evt.room_id, evt.sender)
            disabled_webhooks = [w for w in user_webhooks if not w.enabled]
            
            if not disabled_webhooks:
                await self._send_text_reply(evt, "❌ No disabled webhooks found to enable.")
                return
            
            if not target:
                # Enable all disabled webhooks for this user
                count = 0
                for webhook in disabled_webhooks:
                    success = await self.db.register_webhook(
                        webhook.room_id,
                        webhook.user_id,
                        webhook.webhook_url,
                        webhook.message_data_template,
                        webhook_id=webhook.id  # Use existing ID to update
                    )
                    if success:
                        count += 1
                
                if count > 0:
                    await self._send_text_reply(evt, f"✅ {count} webhook{'s' if count != 1 else ''} enabled successfully.")
                    self.log.info(f"{count} webhooks enabled for user {evt.sender} in room {evt.room_id}")
                else:
                    await self._send_text_reply(evt, "❌ Failed to enable webhooks.")
            
            elif target.isdigit():
                # Enable by webhook ID
                webhook_id = int(target)
                webhook = next((w for w in disabled_webhooks if w.id == webhook_id), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No disabled webhook found with ID {webhook_id}.")
                    return
                
                success = await self.db.register_webhook(
                    webhook.room_id,
                    webhook.user_id,
                    webhook.webhook_url,
                    webhook.message_data_template,
                    webhook_id=webhook.id
                )
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook ID {webhook_id} enabled successfully.")
                    self.log.info(f"Webhook ID {webhook_id} enabled for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to enable webhook ID {webhook_id}.")
            
            else:
                # Enable by URL
                webhook = next((w for w in disabled_webhooks if w.webhook_url == target), None)
                
                if not webhook:
                    await self._send_text_reply(evt, f"❌ No disabled webhook found with URL: {target}")
                    return
                
                success = await self.db.register_webhook(
                    webhook.room_id,
                    webhook.user_id,
                    webhook.webhook_url,
                    webhook.message_data_template,
                    webhook_id=webhook.id
                )
                
                if success:
                    await self._send_text_reply(evt, f"✅ Webhook enabled successfully: {target}")
                    self.log.info(f"Webhook URL {target} enabled for user {evt.sender}")
                else:
                    await self._send_text_reply(evt, f"❌ Failed to enable webhook: {target}")
                
        except Exception as e:
            self.log.error(f"Failed to enable webhook: {e}")
            await self._send_text_reply(evt, f"❌ Failed to enable webhook: {str(e)}")

    @webhook_command.subcommand("list", help="List all webhooks in this room")
    async def list_webhooks(self, evt: MessageEvent) -> None:
        """List all webhook registrations in the current room."""
        try:
            webhooks = await self.db.list_webhooks_for_room(evt.room_id)
            
            if not webhooks:
                await self._send_text_reply(evt, "No webhooks registered in this room.")
                return

            response = "**Webhooks in this room:**\n\n"
            for webhook in webhooks:
                status = "🟢 Active" if webhook.enabled else "🔴 Disabled"
                response += (
                    f"* **ID {webhook.id}:** `{webhook.webhook_url} ({status})`\n\n"
                )
            
            await self._send_text_reply(evt, response)
            
        except Exception as e:
            self.log.error(f"Failed to list webhooks: {e}")
            await self._send_text_reply(evt, f"❌ Failed to list webhooks: {str(e)}")

    # @webhook_command.subcommand("configure", help="Configure message data template for a webhook")
    # @command.argument("webhook_id", pass_raw=False, required=True)
    # @command.argument("template", pass_raw=True, required=False)
    # async def configure_webhook(self, evt: MessageEvent, webhook_id: str, template: str = "") -> None:
    #     """Configure the message data template for a specific webhook."""
    #     if not webhook_id.isdigit():
    #         await self._send_text_reply(evt, "❌ Webhook ID must be a number. Use `!webhook status` to see your webhook IDs.")
    #         return
            
    #     webhook_id_int = int(webhook_id)
    #     template = template.strip()
        
    #     try:
    #         # Verify webhook belongs to user
    #         webhook = await self.db.get_webhook_by_id(webhook_id_int)
    #         if not webhook or webhook.user_id != evt.sender:
    #             await self._send_text_reply(evt, f"❌ No webhook found with ID {webhook_id_int} or you don't own it.")
    #             return
            
    #         if not template:
    #             # Show help and current template
    #             default_template = self.config.message_data_template
    #             current_template = webhook.message_data_template or default_template
                
    #             available_vars = "event_id, room_id, sender, timestamp, message_type, body, formatted_body, format"
    #             template_str = json.dumps(current_template, indent=2)
                
    #             await self._send_text_reply(evt,
    #                 f"**Configure Message Template for Webhook ID {webhook_id_int}**\n\n"
    #                 f"**Current template:**\n```json\n{template_str}\n```\n\n"
    #                 f"**Available variables:** {available_vars}\n\n"
    #                 f"**Usage:**\n"
    #                 f"`!webhook configure {webhook_id_int} {{\"body\": \"{{body}}\", \"sender\": \"{{sender}}\"}}`\n\n"
    #                 f"**Example templates:**\n"
    #                 f"• Simple: `{{\"message\": \"{{body}}\", \"from\": \"{{sender}}\"}}`\n"
    #                 f"• Discord: `{{\"content\": \"{{body}}\", \"username\": \"{{sender}}\"}}`\n"
    #                 f"• Slack: `{{\"text\": \"{{body}}\", \"channel\": \"{{room_id}}\"}}`"
    #             )
    #             return

    #         # Parse and validate JSON template
    #         try:
    #             new_template = json.loads(template)
                
    #             if not isinstance(new_template, dict):
    #                 await self._send_text_reply(evt, "❌ Template must be a JSON object (dictionary).")
    #                 return
                
    #             # Validate that all values are strings for templating
    #             for key, value in new_template.items():
    #                 if not isinstance(value, str):
    #                     await self._send_text_reply(evt, f"❌ Template value for '{key}' must be a string. Got: {type(value).__name__}")
    #                     return
                
    #         except json.JSONDecodeError as e:
    #             await self._send_text_reply(evt, f"❌ Invalid JSON format: {str(e)}\n\nPlease provide a valid JSON object.")
    #             return
            
    #         # Update the template
    #         success = await self.db.update_message_template(
    #             webhook_id=webhook_id_int,
    #             user_id=evt.sender,
    #             message_data_template=new_template,
    #         )
            
    #         if success:
    #             template_str = json.dumps(new_template, indent=2)
    #             await self._send_text_reply(evt,
    #                 f"✅ Message template updated for webhook ID {webhook_id_int}!\n\n"
    #                 f"**New template:**\n```json\n{template_str}\n```"
    #             )
    #         else:
    #             await self._send_text_reply(evt, "❌ Failed to update template. Please try again.")
                
    #     except Exception as e:
    #         self.log.error(f"Failed to configure webhook template: {e}")
    #         await self._send_text_reply(evt, f"❌ Failed to configure template: {str(e)}")

    # @webhook_command.subcommand("template", help="Show message template for a webhook")
    # @command.argument("webhook_id", pass_raw=False, required=True)
    # async def show_template(self, evt: MessageEvent, webhook_id: str) -> None:
    #     """Show the current message data template for a webhook."""
    #     if not webhook_id.isdigit():
    #         await self._send_text_reply(evt, "❌ Webhook ID must be a number. Use `!webhook status` to see your webhook IDs.")
    #         return
            
    #     webhook_id_int = int(webhook_id)
        
    #     try:
    #         # Verify webhook belongs to user
    #         webhook = await self.db.get_webhook_by_id(webhook_id_int)
    #         if not webhook or webhook.user_id != evt.sender:
    #             await self._send_text_reply(evt, f"❌ No webhook found with ID {webhook_id_int} or you don't own it.")
    #             return

    #         template = webhook.message_data_template or self.config.message_data_template
    #         template_type = "Custom" if webhook.message_data_template else "Default"
            
    #         template_str = json.dumps(template, indent=2)
            
    #         await self._send_text_reply(evt,
    #             f"**{template_type} Message Template for Webhook ID {webhook_id_int}:**\n"
    #             f"```json\n{template_str}\n```\n\n"
    #             f"**Available variables:** event_id, room_id, sender, timestamp, message_type, body, formatted_body, format"
    #         )
            
    #     except Exception as e:
    #         self.log.error(f"Failed to show template: {e}")
    #         await self._send_text_reply(evt, f"❌ Failed to show template: {str(e)}")

    # @webhook_command.subcommand("reset-template", help="Reset webhook template to default")
    # @command.argument("webhook_id", pass_raw=False, required=True)
    # async def reset_template(self, evt: MessageEvent, webhook_id: str) -> None:
    #     """Reset the message data template to default for a webhook."""
    #     if not webhook_id.isdigit():
    #         await self._send_text_reply(evt, "❌ Webhook ID must be a number. Use `!webhook status` to see your webhook IDs.")
    #         return
            
    #     webhook_id_int = int(webhook_id)
        
    #     try:
    #         # Verify webhook belongs to user
    #         webhook = await self.db.get_webhook_by_id(webhook_id_int)
    #         if not webhook or webhook.user_id != evt.sender:
    #             await self._send_text_reply(evt, f"❌ No webhook found with ID {webhook_id_int} or you don't own it.")
    #             return

    #         success = await self.db.update_message_template(
    #             webhook_id=webhook_id_int,
    #             user_id=evt.sender,
    #             message_data_template=None,  # Reset to None to use default
    #         )
            
    #         if success:
    #             default_template = self.config.message_data_template
    #             template_str = json.dumps(default_template, indent=2)
                
    #             await self._send_text_reply(evt,
    #                 f"✅ Message template reset to default for webhook ID {webhook_id_int}!\n\n"
    #                 f"**Default template:**\n```json\n{template_str}\n```"
    #             )
    #         else:
    #             await self._send_text_reply(evt, "❌ Failed to reset template. Please try again.")
                
    #     except Exception as e:
    #         self.log.error(f"Failed to reset template: {e}")
    #         await self._send_text_reply(evt, f"❌ Failed to reset template: {str(e)}")

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
                                        await self._send_text_reply(original_evt, formatted_response)
                                            
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