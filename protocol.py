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


class JSONProtocol:
    """Protocol using JSON"""

    def encode(message: Message) -> bytes:
        # return json.dumps(message.__dict__).encode()
        data = {
            "cmd": message.cmd,
            'src': message.src,
            "to": message.to,
            "body": message.body,
            "error": message.error
        }
        json_str = json.dumps(data)
        # print(json_str)
        return json_str.encode()
    
    def decode(data: bytes) -> Message:
        # return Message(**json.loads(data.decode()))
        parsed = json.loads(data.decode())
        return Message(
            cmd=parsed['cmd'],
            src=parsed.get('from', ''),
            to=parsed.get('to', ''),
            body=parsed.get('body', ''),
            error=parsed.get('error', False)
        )


class CustomProtocol:
    """
    Custom binary protocol format:
    [1 byte: cmd length][cmd bytes][1 byte: src length][src bytes][1 byte: to length][to bytes][2 bytes: body length][body bytes][1 byte: error]
    """
    
    def encode(message: Message) -> bytes:
        # Convert strings to bytes
        cmd_bytes = message.cmd.encode()
        src_bytes = message.src.encode()
        to_bytes = message.to.encode()
        body_bytes = message.body.encode()
        
        # Create length prefixes
        cmd_len = len(cmd_bytes).to_bytes(1, 'big')
        src_len = len(src_bytes).to_bytes(1, 'big')
        to_len = len(to_bytes).to_bytes(1, 'big')
        body_len = len(body_bytes).to_bytes(2, 'big')
        error_byte = b'\x01' if message.error else b'\x00'
        
        # Combine all parts
        return (cmd_len + cmd_bytes + 
                src_len + src_bytes + 
                to_len + to_bytes + 
                body_len + body_bytes + 
                error_byte)

    def decode(data: bytes) -> Message:
        pos = 0
        cmd_len = data[pos]
        pos += 1
        cmd = data[pos:pos+cmd_len].decode()
        pos += cmd_len
        
        # src
        src_len = data[pos]
        pos += 1
        src = data[pos:pos+src_len].decode()
        pos += src_len
        
        # to
        to_len = data[pos]
        pos += 1
        to = data[pos:pos+to_len].decode()
        pos += to_len
        
        # body
        body_len = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        body = data[pos:pos+body_len].decode()
        pos += body_len
        
        # error
        error = data[pos] == 1
        
        return Message(cmd=cmd, src=src, to=to, body=body, error=error) 
#     def encode(message: Message) -> bytes: