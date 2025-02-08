import pytest
from server import ChatServer
from protocol import Message, JSONProtocol

@pytest.fixture
def chat_server():
    return ChatServer("localhost", 5000)

def test_server_initialization(chat_server):
    assert chat_server.host == "localhost"
    assert chat_server.port == 5000

def test_server_message_handling(chat_server):
    client_mock = MagicMock()
    message = Message(cmd="login", src="user1", body="password")
    data = JSONProtocol.encode(message)
    client_mock.recv.return_value = len(data).to_bytes(4, 'big') + data
    with patch.object(chat_server, 'protocol') as proto_mock:
        proto_mock.decode.return_value = message
        chat_server.handle_client(client_mock, ("127.0.0.1", 12345))
        proto_mock.decode.assert_called()