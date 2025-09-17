# Webhook Plugin for Maubot

A Maubot plugin that provides both incoming and outgoing webhook functionality for Matrix rooms.

## Features

### Incoming Webhooks (NEW!)
- **Receive messages from external services**: Create webhook endpoints that external services can POST to
- **Unique URLs and API keys**: Each webhook gets a unique URL and API key for security
- **Automatic message forwarding**: Messages sent to webhook endpoints are posted to Matrix rooms
- **User-specific endpoints**: Each user can create their own webhook endpoints

### Outgoing Webhooks
- **Multiple webhooks per user**: Users can register multiple webhook URLs in the same room
- **Message forwarding**: All messages in rooms with registered webhooks are automatically forwarded via POST requests
- **Configurable message templates**: Customize the data structure sent to webhooks
- **Webhook responses**: If a webhook returns a JSON response with a "response" field, the bot will send it back to the chat
- **Complete webhook lifecycle management**: Register, list, disable, enable, and delete webhooks
- **Per-webhook configuration**: Each webhook can have its own message data template
- **User isolation**: Users can only manage their own webhook registrations

## Commands

### Outgoing Webhook Management
- `!webhook register <url>` - Register a new outgoing webhook URL for your user in the current room
- `!webhook unregister [id|url]` - Delete outgoing webhook(s) permanently from database
  - `!webhook unregister` - Delete all your webhooks
  - `!webhook unregister 123` - Delete webhook with ID 123
  - `!webhook unregister https://...` - Delete webhook with specific URL
- `!webhook disable [id|url]` - Disable outgoing webhook(s) temporarily (keeps in database)
  - `!webhook disable` - Disable all your active webhooks
  - `!webhook disable 123` - Disable webhook with ID 123
  - `!webhook disable https://...` - Disable webhook with specific URL
- `!webhook enable [id|url]` - Enable previously disabled outgoing webhook(s)
  - `!webhook enable` - Enable all your disabled webhooks
  - `!webhook enable 123` - Enable webhook with ID 123
  - `!webhook enable https://...` - Enable webhook with specific URL
- `!webhook list` - List all outgoing webhooks in the current room (shows ID, URL, and status)

### Incoming Webhook Management
- `!webhook create` - Create a new incoming webhook endpoint for this room
- `!webhook delete <webhook_id>` - Delete an incoming webhook endpoint

## Incoming Webhooks Usage

When you create an incoming webhook with `!webhook create`, you'll receive:
- A unique webhook URL
- A secure API key

### Sending Messages via Webhook

To send a message to the Matrix room, make a POST request to the webhook URL:

```bash
curl -X POST 'https://your-bot.domain/_matrix/maubot/plugin/xyz.maubot.webhook/webhook/your-webhook-id' \
  -H 'Authorization: Bearer your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{"message": "Hello from external service!"}'
```

### Request Format

The webhook accepts JSON requests with the following fields:
- `message` (required): The text message to send
- `formatted_body` (optional): HTML-formatted version of the message

Example:
```json
{
  "message": "Hello **world**!",
  "formatted_body": "Hello <strong>world</strong>!"
}
```

## Configuration

The plugin supports extensive configuration options in `base-config.yaml`:

### Basic Settings
- `webhook_timeout`: Request timeout in seconds (default: 30)
- `max_webhook_retries`: Maximum number of retry attempts for failed requests (default: 3)
- `webhook_user_agent`: User agent string for outgoing webhook requests (default: "Maubot-Webhook-Plugin/1.0")

### Default Message Data Template (Outgoing Webhooks)
- `message_data_template`: Define the default structure of data sent to outgoing webhooks (JSON format in config)
- `custom_fields`: Add custom static fields to all outgoing webhook payloads
- `include_empty_fields`: Whether to include null/empty fields (default: false)

### Response Template
- `response_template`: Template for formatting webhook responses sent back to chat

## Current Implementation Status

### ✅ Implemented Features
- **Outgoing webhooks**: Full lifecycle management (register, unregister, disable, enable, list)
- **Incoming webhooks**: Create and delete endpoints with unique URLs and API keys
- **HTTP endpoint**: Receive POST requests and forward to Matrix rooms
- **Security**: API key validation and user isolation

### ⚠️ Missing Features
- **Incoming webhook listing**: Command to list incoming webhooks (planned)
- **Incoming webhook management**: Disable/enable for incoming webhooks (planned)

## Database Schema

The plugin creates two tables:

### `webhook_registration` (Outgoing Webhooks)
- `id`: Unique identifier
- `room_id`: Matrix room ID
- `user_id`: Matrix user ID  
- `webhook_url`: The registered webhook URL
- `enabled`: Whether the webhook is active
- `created_at`: Registration timestamp
- `message_data_template`: Custom message template

### `incoming_webhook` (Incoming Webhooks)
- `id`: Unique identifier
- `room_id`: Matrix room ID
- `user_id`: Matrix user ID
- `webhook_id`: Unique webhook identifier (UUID)
- `api_key`: Secure API key for authentication
- `enabled`: Whether the webhook is active
- `created_at`: Creation timestamp
- `last_used`: Last usage timestamp

## Installation

1. Build the plugin using maubot's build system
2. Upload the `.mbp` file to your maubot instance
3. Create a new instance and configure it as needed

## Examples

### Outgoing Webhooks
```bash
# Register a webhook to receive Matrix messages
!webhook register https://example.com/hook

# List all webhooks (shows IDs and status)
!webhook list

# Temporarily disable a webhook
!webhook disable 123

# Re-enable it later
!webhook enable 123

# Permanently delete a webhook
!webhook unregister 123
```

### Incoming Webhooks
```bash
# Create an incoming webhook endpoint
!webhook create

# Delete an incoming webhook
!webhook delete abc-123-def-456
```

### External Service Integration
```bash
# Send message via incoming webhook
curl -X POST 'https://your-bot.domain/_matrix/maubot/plugin/xyz.maubot.webhook/webhook/abc-123-def' \
  -H 'Authorization: Bearer your-secure-api-key-here' \
  -H 'Content-Type: application/json' \
  -d '{"message": "Hello from external service!"}'
```

## Security Considerations

### Outgoing Webhooks
- Only HTTP and HTTPS URLs are accepted
- Webhook requests have configurable timeouts
- Failed requests are retried with exponential backoff
- User isolation: Users can only manage their own webhooks

### Incoming Webhooks
- Each webhook has a unique UUID and secure API key
- API keys are validated on every request
- User isolation: Users can only delete their own webhooks
- Last usage tracking for monitoring