# Engineering Notebook

## Protocol Comparison

### JSON Protocol
Messages are encoded as JSON objects with the following fields:
- `cmd`: Command type (login, create, send, etc.)
- `src`: Source username
- `to`: Destination username
- `body`: Message content
- `error`: Error flag

### Custom Binary Protocol
```
[1 byte: cmd length][cmd bytes]
[1 byte: src length][src bytes]
[1 byte: to length][to bytes]
[2 bytes: body length][body bytes]
[1 byte: error]
```

Comparison:
JSON encoded message (bytes):
```
json_msg = {"cmd": "login", "src": "alice", "to": "server", "body": "This is a test message", "error": False}
```
Size: 98 bytes

Custom encoded message (bytes):
```
custom_msg = b'\x05login\x05alice\x06server\x00\x1bThis is a test message\x00'
```
Size: 44 bytes

Comparison:
- JSON protocol size:   98 bytes
- Custom protocol size: 44 bytes

