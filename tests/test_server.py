import pytest
from server import ChatServer
from protocol import Message, JSONProtocol
from unittest.mock import MagicMock
from unittest.mock import patch

@pytest.fixture
def chat_server():
    return ChatServer("localhost", 5001)

def test_server_initialization(chat_server):
    assert chat_server.host == "localhost"
    assert chat_server.port == 5001

def test_server_message_handling(chat_server):
    client_mock = MagicMock()
    message = Message(cmd="login", src="user1", body="password")
    
    data = JSONProtocol.encode(message)
    
    # Simulate message then EOF
    client_mock.send = (
        len(data).to_bytes(4, 'big') + data,
        b''  # EOF
    )
    
    with patch.object(chat_server, 'protocol') as proto_mock:
        proto_mock.decode.return_value = message
        chat_server.handle_client(client_mock, ("127.0.0.1", 12345))
        
        # Ensure the message was decoded
        proto_mock.decode.assert_called()