import socket
import threading
import os
import argparse
from collections import OrderedDict
from typing import Dict, Optional
from datetime import datetime
from protocol import Message, JSONProtocol, CustomProtocol

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
        self.server.bind((host, port))
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
                    if username in self.users:
                        response = Message(cmd="create", body="Username already exists", error=True)
                    else:
                        self.users[username] = message.body
                        self.messages[username] = []  # Initialize message queue for new user
                        response = Message(cmd="create", body="Account created", to=username)
                elif cmd == "login":
                    if username not in self.users:
                        response = Message(cmd="login", body="Username/Password error", error=True)
                    elif username in self.current_users:
                        response = Message(cmd="login", body="Already logged in elsewhere", error=True)
                    elif self.users[username] != message.body:
                        response = Message(cmd="login", body="Username/Password error", error=True)
                    else:
                        self.current_users[username] = client
                        response = Message(cmd="login", body=f"Login successful", to=username)
                elif cmd == "logoff":
                    if username in self.current_users:
                        self.current_users.pop(username)
                        response = Message(cmd="logoff", body="Logged out successfully")
                elif cmd == "list":
                    pattern = message.body if message.body else "all"
                    matching_users = []
                    for user in self.users.keys():
                        if pattern == "all" or pattern in user:
                            matching_users.append(user)
                    response = Message(cmd="list", body=",".join(matching_users))
                elif cmd == "send":
                    recipient = message.to
                    content = message.body
                    if not content or not recipient:
                        response = Message(cmd="send", body="Message content and recipient are required", error=True)
                    else:
                        # Sending message if recipient online, else store in messages    
                        if recipient in self.current_users:
                            recipient_socket = self.current_users[recipient]
                            notification = Message(cmd="deliver", src=username, body=content)
                            encoded = self.protocol.encode(notification)
                            recipient_socket.send(len(encoded).to_bytes(4, 'big'))
                            recipient_socket.send(encoded)
                        else:
                            if recipient not in self.messages:
                                self.messages[recipient] = []
                            self.messages[recipient].append((username, content))
                        response = Message(cmd="send", body="Message sent successfully")
                elif cmd == "deliver":
                    if username in self.messages:
                        messages = self.messages[username]
                        for sender, content in messages:
                            notification = Message(cmd="deliver", src=sender, body=content)
                            encoded = self.protocol.encode(notification)
                            client.send(len(encoded).to_bytes(4, 'big'))
                            client.send(encoded)
                        self.messages[username] = []
                elif cmd == "delete":
                    if username not in self.users:
                        response = Message(cmd="delete", body="User does not exist", error=True)
                    else:
                        self.users.pop(username)
                        if username in self.messages:
                            self.messages.pop(username)
                        response = Message(cmd="delete", body="Account deleted")

                    
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
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat Server')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--custom_mode', action='store_true')
    
    args = parser.parse_args()  

    server = ChatServer(args.host, args.port, args.custom_mode)
    server.start()