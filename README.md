# Chatbot app

## Installation

Only standard python libraries are requires

## Starting the Server

```bash
# Start server with JSON protocol (default)
python server.py --host localhost --port 5000

# Start server with custom binary protocol
python server.py --host localhost --port 5000 --custom_mode
```

Server arguments:
- `--host`: Server host address (default: localhost)
- `--port`: Server port number (default: 5000)
- `--custom_mode`: Use custom binary protocol instead of JSON

## Starting the Client

```bash
# Start client with JSON protocol (default)
python client.py --host localhost --port 5000

# Start client with custom binary protocol
python client.py --host localhost --port 5000 --custom_mode
```

Client arguments:
- `--host`: Server host address (default: localhost)
- `--port`: Server port number (default: 5000)
- `--custom_mode`: Use custom binary protocol instead of JSON

## Features

- Create account
- Login/Logout
- Delete account
- View online users
- Send messages to online users
- Store messages for offline users
- Read message history
- Real-time message delivery

## Testing
`export PYTHONPATH=$(pwd)`