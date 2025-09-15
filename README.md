# Webhook Plugin for Maubot

A Maubot plugin that allows users to register webhook URLs and automatically forwards all messages in a room to the registered webhooks.

## Features

- **Register webhooks**: Users can register webhook URLs using `!webhook register <url>`
- **Message forwarding**: All messages in rooms with registered webhooks are automatically forwarded via POST requests
- **Webhook responses**: If a webhook returns a JSON response with a "response" field, the bot will send it back to the chat
- **Multiple webhooks**: Multiple users can register different webhooks in the same room
- **Webhook management**: List, check status, and unregister webhooks

## Commands

- `!webhook register <url>` - Register a webhook URL for your user in the current room
- `!webhook unregister` - Unregister your webhook in the current room
- `!webhook list` - List all webhooks registered in the current room
- `!webhook status` - Check the status of your webhook in the current room

## Configuration

The plugin supports extensive configuration options in `base-config.yaml`:

### Basic Settings
- `webhook_timeout`: Request timeout in seconds (default: 30)
- `max_webhook_retries`: Maximum number of retry attempts for failed requests (default: 3)
- `webhook_user_agent`: User agent string for webhook requests (default: "Maubot-Webhook-Plugin/1.0")

### Message Data Template
- `message_data_template`: Define the structure of data sent to webhooks
- `custom_fields`: Add custom static fields to all webhook payloads
- `include_empty_fields`: Whether to include null/empty fields (default: false)

### Response Template
- `response_template`: Template for formatting webhook responses sent back to chat

### Example Configuration
```yaml
message_data_template:
  event_id: "{event_id}"
  room: "{room_id}"
  user: "{sender}"
  timestamp: "{timestamp}"
  type: "{message_type}"
  content: "{body}"
  html_content: "{formatted_body}"
  format: "{format}"

custom_fields:
  source: "maubot-webhook"
  version: "1.0"
  environment: "production"

response_template: "🤖 **Bot says:** {response}"
include_empty_fields: false
```

## Webhook Payload

The payload structure is fully configurable via the `message_data_template` in your config. The default payload includes:

```json
{
    "event_id": "message_event_id",
    "room_id": "!room_id:example.com",
    "sender": "@user:example.com",
    "timestamp": 1640995200000,
    "message_type": "m.text",
    "body": "message text",
    "formatted_body": "formatted message (if available)",
    "format": "org.matrix.custom.html (if available)",
    "source": "maubot-webhook",
    "version": "1.0"
}
```

### Available Template Variables
- `{event_id}`: Matrix event ID
- `{room_id}`: Matrix room ID  
- `{sender}`: Matrix user ID of sender
- `{timestamp}`: Message timestamp
- `{message_type}`: Matrix message type (m.text, m.image, etc.)
- `{body}`: Plain text message content
- `{formatted_body}`: HTML formatted content (if available)
- `{format}`: Message format type (if available)

### Custom Payload Example
You can customize the payload structure completely:

```yaml
message_data_template:
  id: "{event_id}"
  chat_room: "{room_id}"
  user: "{sender}"
  time: "{timestamp}"
  message: "{body}"
  
custom_fields:
  bot_name: "webhook-forwarder"
  instance_id: "prod-01"
```

This would produce:
```json
{
    "id": "message_event_id",
    "chat_room": "!room_id:example.com", 
    "user": "@user:example.com",
    "time": 1640995200000,
    "message": "message text",
    "bot_name": "webhook-forwarder",
    "instance_id": "prod-01"
}
```

## Webhook Response

Your webhook can optionally return a JSON response that will be sent back to the chat:

```json
{
    "response": "This message will be sent back to the chat"
}
```

## Installation

1. Build the plugin using maubot's build system
2. Upload the `.mbp` file to your maubot instance
3. Create a new instance and configure it as needed

## Database

The plugin creates a `webhook_registration` table to store webhook registrations with the following schema:

- `id`: Unique identifier
- `room_id`: Matrix room ID
- `user_id`: Matrix user ID
- `webhook_url`: The registered webhook URL
- `enabled`: Whether the webhook is active
- `created_at`: Registration timestamp

## Security Considerations

- Only HTTP and HTTPS URLs are accepted
- Webhook requests have configurable timeouts to prevent hanging
- Failed webhook requests are retried with exponential backoff
- Users can only manage their own webhook registrations