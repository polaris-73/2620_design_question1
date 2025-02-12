import socket
import threading
import os
import argparse
from collections import OrderedDict
from typing import Dict, Optional
from datetime import datetime
from protocol import Message, JSONProtocol, CustomProtocol
import uuid

class ChatServer:
    """ Chat server """
    def __init__(self, host: str, port: int, custom_mode: bool = False):
        '''
        Initialize the server
        host: the host to bind the server to
        port: the port to bind the server to
        custom_mode: whether to use the custom protocol
        '''
        self.host = host
        self.port = port
        self.protocol = JSONProtocol if not custom_mode else CustomProtocol
        self.users = OrderedDict()
        self.messages = OrderedDict()
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow reuse of the address
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to all available interfaces
        self.server.bind(('0.0.0.0', port))
        self.current_users = {}
    
    def handle_client(self, client: socket.socket, address):
        print(f"Connection from {address}")
        try:
            while self.running:
                length_bytes = client.recv(4)
                if not length_bytes:
                    break
                msg_length = int.from_bytes(length_bytes, 'big')
                data = client.recv(msg_length)
                # print('if not data', data)
                # if not data:
                #     break
                message = self.protocol.decode(data)
                # print(message)
                cmd = message.cmd
                username = message.src
                response = None
                # import pdb; pdb.set_trace()

                # Getting the response from the server
                if cmd == "create":
                    response = self.handle_create(username, message, client)
                elif cmd == "login":
                    response = self.handle_login(username, message, client)
                elif cmd == "logoff":
                    response = self.handle_logoff(username, message)
                elif cmd == "list":
                    response = self.handle_list(message)
                elif cmd == "send":
                    response = self.handle_send(username, message)
                elif cmd == "deliver":
                    response = self.handle_deliver(username, message, client)
                elif cmd == "delete":
                    response = self.handle_delete(username, message)
                elif cmd == "delete_msgs":
                    response = self.handle_delete_messages(username, message)

                if response:
                    encoded = self.protocol.encode(response)
                    # Send message length first
                    client.send(len(encoded).to_bytes(4, 'big'))
                    client.send(encoded)
        except Exception as e:
            print(f"Error in handling client: {e}")
        finally:
            # Clean up connection
            for username, conn in list(self.current_users.items()):
                if conn == client:
                    self.current_users.pop(username)
                    break
            client.close()
            print(f"Connection closed: {address}")

    def start(self):
        self.server.listen()
        print(f"Server running on {self.host}:{self.port}")
        try:
            while self.running:
                client, address = self.server.accept()
                thread = threading.Thread(target=self.handle_client, args=(client, address))
                thread.daemon = True
                thread.start()
        except KeyboardInterrupt:
            self.running = False
            self.server.close()
            print("Server down.")
        finally:
            self.running = False
            self.server.close()
    
    def handle_create(self, username: str, message: Message, client: socket.socket):
        if username in self.users:
            response = Message(cmd="create", body="Username already exists", error=True)
        else:
            self.users[username] = message.body
            self.messages[username] = []  # Initialize message queue for new user
            response = Message(cmd="create", body="Account created", to=username)
            self.current_users[username] = client
        return response
    def handle_login(self, username: str, message: Message, client: socket.socket):
        if username not in self.users:
            response = Message(cmd="login", body="Username/Password error", error=True)
        elif self.users[username] != message.body:
            response = Message(cmd="login", body="Username/Password error", error=True)
        else:
            self.current_users[username] = client
            # Initialize message queue if not exists
            if username not in self.messages:
                self.messages[username] = []
            response = Message(cmd="login", body=f"Login successful", to=username)
        return response
    def handle_logoff(self, username: str, message: Message):
        if username in self.current_users:
            self.current_users.pop(username)
            response = Message(cmd="logoff", body="Logged out successfully")
        return response

    def handle_list(self, message: Message):
        pattern = message.body if message.body else "all"
        matching_users = []
        for user in self.users.keys():
            if pattern == "all" or pattern in user:
                matching_users.append(user)
        response = Message(cmd="list", body=",".join(matching_users))
        return response

    def handle_send(self, username: str, message: Message):
        recipient = message.to
        content = message.body
        if not content or not recipient:
            response = Message(cmd="send", body="Message content and recipient are required", error=True)
        elif recipient not in self.users:
            response = Message(cmd="send", body="Recipient not found", error=True)
        else:
            try:
                # Use client-provided message ID
                msg_id = message.msg_ids[0] if message.msg_ids else None
                if recipient in self.current_users:
                    # Deliver immediately if recipient is online
                    recipient_socket = self.current_users[recipient]
                    notification = Message(cmd="deliver", src=username, body=content, msg_ids=[msg_id] if msg_id else None)
                    try:
                        encoded = self.protocol.encode(notification)
                        recipient_socket.send(len(encoded).to_bytes(4, 'big'))
                        recipient_socket.send(encoded)
                        print(f"Message delivered immediately to {recipient}")
                    except Exception as e:
                        print(f"Failed to deliver message to {recipient}: {e}")
                        # If immediate delivery fails, store the message
                        if recipient not in self.messages:
                            self.messages[recipient] = []
                        self.messages[recipient].append((msg_id, username, content))
                else:
                    # Store message for offline recipient
                    if recipient not in self.messages:
                        self.messages[recipient] = []
                    self.messages[recipient].append((msg_id, username, content))
                    print(f"Message stored for offline user {recipient}")
                response = Message(cmd="send", body="Message sent successfully")
            except Exception as e:
                print(f"Error in handle_send: {e}")
                response = Message(cmd="send", body="Failed to send message", error=True)
        return response
    def handle_deliver(self, username: str, message: Message, client: socket.socket):

        messages = self.messages[username]

        # Apply limit if specified
        limit = message.limit if message.limit > 0 else len(messages)
        messages_to_send = messages[:limit]
        
        for msg_id, sender, content in messages_to_send:
            notification = Message(cmd="deliver", src=sender, body=content, msg_ids=[msg_id])
            encoded = self.protocol.encode(notification)
            client.send(len(encoded).to_bytes(4, 'big'))
            client.send(encoded)
        
        # Keep remaining messages
        self.messages[username] = messages[limit:]
        return None
    def handle_delete_messages(self, username: str, message: Message):
        if not message.msg_ids:
            return Message(cmd="delete_msgs", body="No message IDs specified", error=True)
        
        if username in self.messages:
            # Filter out messages that should be deleted
            self.messages[username] = [
                msg for msg in self.messages[username] 
                if msg[0] not in message.msg_ids
            ]
        return Message(cmd="delete_msgs", body="Messages deleted successfully")
    def handle_delete(self, username: str, message: Message):
        if username not in self.users:
            response = Message(cmd="delete", body="User does not exist", error=True)
        else:
            self.users.pop(username)
            if username in self.current_users:
                self.current_users.pop(username)
            if username in self.messages:
                self.messages.pop(username)
            # Remove user's messages from other users' queues
            for user_msgs in self.messages.values():
                user_msgs[:] = [msg for msg in user_msgs if msg[1] != username]
            response = Message(cmd="delete", body="Account deleted")
        return response
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat Server')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--custom_mode', action='store_true')
    
    args = parser.parse_args()  

    server = ChatServer(args.host, args.port, args.custom_mode)
    server.start()