# Webhook Plugin for Maubot

A Maubot plugin that allows users to register webhook URLs and automatically forwards all messages in a room to the registered webhooks.

## Features

- **Multiple webhooks per user**: Users can register multiple webhook URLs in the same room
- **Message forwarding**: All messages in rooms with registered webhooks are automatically forwarded via POST requests
- **Configurable message templates**: Customize the data structure sent to webhooks
- **Webhook responses**: If a webhook returns a JSON response with a "response" field, the bot will send it back to the chat
- **Complete webhook lifecycle management**: Register, list, disable, enable, and delete webhooks
- **Per-webhook configuration**: Each webhook can have its own message data template
- **User isolation**: Users can only manage their own webhook registrations

## Commands

### Basic Webhook Management
- `!webhook register <url>` - Register a new webhook URL for your user in the current room
- `!webhook register <url> <template>` - Register a webhook with custom message template
- `!webhook list` - List all webhooks in the current room (shows ID, URL, and status)

### Webhook Lifecycle Control
- `!webhook unregister [id|url]` - **Delete** webhook(s) permanently from database
  - `!webhook unregister` - Delete all your webhooks
  - `!webhook unregister 123` - Delete webhook with ID 123
  - `!webhook unregister https://...` - Delete webhook with specific URL
- `!webhook disable [id|url]` - **Disable** webhook(s) temporarily (keeps in database)
  - `!webhook disable` - Disable all your active webhooks
  - `!webhook disable 123` - Disable webhook with ID 123
  - `!webhook disable https://...` - Disable webhook with specific URL
- `!webhook enable [id|url]` - **Enable** previously disabled webhook(s)
  - `!webhook enable` - Enable all your disabled webhooks
  - `!webhook enable 123` - Enable webhook with ID 123
  - `!webhook enable https://...` - Enable webhook with specific URL

## Configuration

The plugin supports extensive configuration options in `base-config.yaml`:

### Basic Settings
- `webhook_timeout`: Request timeout in seconds (default: 30)
- `max_webhook_retries`: Maximum number of retry attempts for failed requests (default: 3)
- `webhook_user_agent`: User agent string for webhook requests (default: "Maubot-Webhook-Plugin/1.0")

### Default Message Data Template
- `message_data_template`: Define the default structure of data sent to webhooks (JSON format in config)
- `custom_fields`: Add custom static fields to all webhook payloads
- `include_empty_fields`: Whether to include null/empty fields (default: false)

### Response Template
- `response_template`: Template for formatting webhook responses sent back to chat

### Per-Webhook Templates
Users can set custom templates for individual webhooks during registration using key=value format:
- **Global default**: Set in `base-config.yaml` (JSON format)
- **Per-webhook override**: Set during registration with key=value format
- **Template inheritance**: Webhooks without custom templates use the global default

### Example Configuration
```yaml
# Global default template (JSON format)
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

## Message Template Formats

### Global Configuration (JSON Format)
In `base-config.yaml`, use standard YAML/JSON structure:
```yaml
message_data_template:
  event_id: "{event_id}"
  room_id: "{room_id}"
  sender: "{sender}"
  message: "{body}"
```

### Template Inheritance
1. **Default**: Webhooks use global template from config
2. **Override**: Use key=value format during registration to customize individual webhooks  
3. **Fallback**: If no template specified during registration, uses built-in default template

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

- `id`: Unique identifier (used for webhook management commands)
- `room_id`: Matrix room ID
- `user_id`: Matrix user ID  
- `webhook_url`: The registered webhook URL
- `enabled`: Whether the webhook is active (true/false)
- `created_at`: Registration timestamp
- `message_data_template`: JSON-stored custom message template for this webhook

### Database Operations
- **Register**: Creates new webhook or enables existing one by URL
- **Delete (Unregister)**: Permanently removes webhook from database
- **Disable**: Sets `enabled=false` but keeps webhook in database
- **Enable**: Sets `enabled=true` for disabled webhooks
- **List**: Shows all webhooks (enabled and disabled) with status indicators

## Migration Notes

The database automatically migrates to support multiple webhooks per user and per-webhook message templates. Existing single-webhook installations will be preserved and work normally.

## Examples

### Basic Usage
```bash
# Register a simple webhook
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

## Security Considerations

- Only HTTP and HTTPS URLs are accepted
- Webhook requests have configurable timeouts to prevent hanging
- Failed webhook requests are retried with exponential backoff
- **User isolation**: Users can only manage their own webhook registrations
- **ID-based security**: Webhook operations by ID verify ownership before execution
- **Multiple webhook support**: Each user can have multiple webhooks without conflicts
- **Granular control**: Separate disable/enable vs delete operations for data safety