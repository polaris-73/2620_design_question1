import pytest
from unittest.mock import patch, MagicMock
from client import ChatClientGUI
from protocol import Message, JSONProtocol

@pytest.fixture
def mock_socket():
    with patch("socket.socket") as mock_sock:
        yield mock_sock

def test_client_connect(mock_socket):
    client = ChatClientGUI("localhost", 5000)
    assert client.socket is not None
    mock_socket.return_value.connect.assert_called_with(("localhost", 5000))

def test_send_message(mock_socket):
    client = ChatClientGUI("localhost", 5000)
    client.socket = mock_socket.return_value
    msg = Message(cmd="login", src="test_user", body="password")
    client.send_msg(msg)
    mock_socket.return_value.send.assert_called()

def test_handle_message(mock_socket):
    client = ChatClientGUI("localhost", 5000)
    msg = Message(cmd="login", body="Success!")
    with patch.object(client, 'refresh_users') as refresh_mock:
        client.handle_msg(msg)
        assert client.username is not None
        refresh_mock.assert_called()