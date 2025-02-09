import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from protocol import Message, JSONProtocol, CustomProtocol

def test_json_protocol_encoding_decoding():
    msg = Message(cmd="send", src="user1", to="user2", body="Hello", error=False)
    encoded = JSONProtocol.encode(msg)
    decoded = JSONProtocol.decode(encoded)
    assert msg == decoded

def test_custom_protocol_encoding_decoding():
    msg = Message(cmd="create", src="user3", to="", body="Password123", error=True)
    encoded = CustomProtocol.encode(msg)
    decoded = CustomProtocol.decode(encoded)
    assert msg == decoded