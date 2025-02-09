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
json_msg = {"cmd": "login", "src": "alice", "to": "server", "body": "This is a test message", "error": False, "msg_ids": '8d4a8912-5776-4438-ac14-8b791cfc63f2', "limit": 10}
```
Size: 162 bytes

Custom encoded message (bytes):
```
custom_msg = b'\x05login\x05alice\x06server\x00\x16This is a test message\x00\x00&"8d4a8912-5776-4438-ac14-8b791cfc63f2"\x00\n'
```
Size: 86 bytes

Comparison:
- JSON protocol size:   162 bytes
- Custom protocol size: 86 bytes

