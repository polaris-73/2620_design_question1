from dataclasses import dataclass
import json

@dataclass
class Message:
    """ Message for the protocol """
    cmd: str
    src: str = ""
    to: str = ""
    body: str = ""
    error: bool = False
    msg_ids: list = None  # For message deletion
    limit: int = 0  # For limiting message delivery

msg = Message(cmd="login", src="alice", to="server", body="This is a test message", error=False, msg_ids='8d4a8912-5776-4438-ac14-8b791cfc63f2', limit=10)
class JSONProtocol:
    """Protocol using JSON"""

    def encode(message: Message) -> bytes:
        data = {
            "cmd": message.cmd,
            'src': message.src,
            "to": message.to,
            "body": message.body,
            "error": message.error,
            "msg_ids": message.msg_ids if message.msg_ids is not None else [],
            "limit": message.limit
        }
        json_str = json.dumps(data)
        return json_str.encode()
    
    def decode(data: bytes) -> Message:
        parsed = json.loads(data.decode())
        return Message(
            cmd=parsed['cmd'],
            src=parsed.get('src', ''),
            to=parsed.get('to', ''),
            body=parsed.get('body', ''),
            error=parsed.get('error', False),
            msg_ids=parsed.get('msg_ids', None),
            limit=parsed.get('limit', 0)
        )


class CustomProtocol:
    """
    Custom binary protocol format:
    [1 byte: cmd length][cmd bytes][1 byte: src length][src bytes][1 byte: to length][to bytes]
    [2 bytes: body length][body bytes][1 byte: error][2 bytes: msg_ids length][msg_ids bytes][2 bytes: limit]
    """
    
    def encode(message: Message) -> bytes:
        # Convert strings to bytes
        cmd_bytes = message.cmd.encode()
        src_bytes = message.src.encode()
        to_bytes = message.to.encode()
        body_bytes = message.body.encode()
        msg_ids_bytes = json.dumps(message.msg_ids if message.msg_ids is not None else []).encode()
        
        # Create length prefixes
        cmd_len = len(cmd_bytes).to_bytes(1, 'big')
        src_len = len(src_bytes).to_bytes(1, 'big')
        to_len = len(to_bytes).to_bytes(1, 'big')
        body_len = len(body_bytes).to_bytes(2, 'big')
        msg_ids_len = len(msg_ids_bytes).to_bytes(2, 'big')
        error_byte = b'\x01' if message.error else b'\x00'
        limit_bytes = message.limit.to_bytes(2, 'big')
        
        # Combine all parts
        return (cmd_len + cmd_bytes + 
                src_len + src_bytes + 
                to_len + to_bytes + 
                body_len + body_bytes + 
                error_byte +
                msg_ids_len + msg_ids_bytes +
                limit_bytes)

    def decode(data: bytes) -> Message:
        pos = 0
        
        # Command
        cmd_len = data[pos]
        pos += 1
        cmd = data[pos:pos+cmd_len].decode()
        pos += cmd_len
        
        # Source
        src_len = data[pos]
        pos += 1
        src = data[pos:pos+src_len].decode()
        pos += src_len
        
        # To
        to_len = data[pos]
        pos += 1
        to = data[pos:pos+to_len].decode()
        pos += to_len
        
        # Body
        body_len = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        body = data[pos:pos+body_len].decode()
        pos += body_len
        
        # Error
        error = data[pos] == 1
        pos += 1
        
        # Message IDs
        msg_ids_len = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        msg_ids = json.loads(data[pos:pos+msg_ids_len].decode()) if msg_ids_len > 0 else None
        pos += msg_ids_len
        
        # Limit
        limit = int.from_bytes(data[pos:pos+2], 'big')
        
        return Message(cmd=cmd, src=src, to=to, body=body, error=error, msg_ids=msg_ids, limit=limit)