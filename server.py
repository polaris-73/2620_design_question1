import socket
import threading
import os
import argparse
from collections import OrderedDict
from typing import Dict, Optional, List, Tuple, Any
from datetime import datetime
import uuid
import time
import sys
import logging
import signal

from protocol import Message, JSONProtocol, CustomProtocol
from storage import Storage
from replication import ReplicationServer, ReplicationProtocol

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("server")

class ChatServer:
    """ Chat server """
    def __init__(self, host: str, port: int, data_dir: str, replication_port: int, 
                 peer_servers: List[Tuple[str, str, int]] = None, custom_mode: bool = False):
        '''
        Initialize the server
        host: the host to bind the server to
        port: the port to bind the server to
        data_dir: directory for server data
        replication_port: port for replication server
        peer_servers: list of (peer_id, host, port) tuples for other servers
        custom_mode: whether to use the custom protocol
        '''
        self.host = host
        self.port = port
        self.data_dir = data_dir
        self.replication_port = replication_port
        self.protocol = JSONProtocol if not custom_mode else CustomProtocol
        self.running = True
        self.transitioning = False  # Flag to indicate server is transitioning between states
        
        # Create data directory if it doesn't exist
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize storage
        self.storage = Storage(data_dir)
        
        # Load user data from storage
        self.users = self.storage.get_users()
        self.current_users = {}  # Username -> socket connection
        
        # Initialize replication server
        self.replication = ReplicationServer(
            host=host,
            port=replication_port,
            data_dir=data_dir,
            on_state_change=self._handle_state_change,
            on_data_update=self._handle_data_update
        )
        
        # Connect to peer servers
        self.peer_servers = peer_servers or []
        
        # Initialize server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow reuse of the address
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to all available interfaces
        self.server.bind(('0.0.0.0', port))
    
    def _handle_state_change(self, new_state: str):
        """Handle replication state changes"""
        logger.info(f"Server state changed to {new_state}")
        self.storage.set_server_state(new_state)
        
        # Mark as transitioning to prevent message processing during state change
        self.transitioning = True
        
        if new_state == "PRIMARY":
            # We're now the primary - start accepting clients
            logger.info("Starting to accept client connections as PRIMARY")
        elif new_state == "BACKUP":
            # We're a backup - don't accept new clients
            logger.info("Operating as BACKUP")
            
            # Close all client connections when becoming a backup
            for username, client in list(self.current_users.items()):
                try:
                    # Send notification to client
                    notification = Message(cmd="server_status", body="Server is now in backup mode, please reconnect", error=True)
                    encoded = self.protocol.encode(notification)
                    client.send(len(encoded).to_bytes(4, 'big'))
                    client.send(encoded)
                except:
                    pass
                
                try:
                    client.close()
                except:
                    pass
                    
            # Clear current users
            self.current_users.clear()
            
        # Allow transition to complete
        time.sleep(0.5)
        self.transitioning = False
    
    def _handle_data_update(self, update_type: str, data: Any):
        """Handle data updates from replication protocol"""
        logger.debug(f"Received data update: {update_type}")
        
        if update_type == "ADD_USER":
            username = data["username"]
            password = data["password"]
            self.users[username] = password
            
        elif update_type == "DELETE_USER":
            username = data["username"]
            if username in self.users:
                del self.users[username]
            
        elif update_type == "ADD_MESSAGE":
            to_username = data["to"]
            from_username = data["from"]
            content = data["content"]
            msg_id = data["msg_id"]
            
            # Only deliver messages immediately if server is PRIMARY
            if self.storage.get_server_state() == "PRIMARY" and to_username in self.current_users:
                try:
                    client = self.current_users[to_username]
                    notification = Message(cmd="deliver", src=from_username, body=content, msg_ids=[msg_id])
                    encoded = self.protocol.encode(notification)
                    client.send(len(encoded).to_bytes(4, 'big'))
                    client.send(encoded)
                    logger.info(f"Message from {from_username} delivered to {to_username}")
                except Exception as e:
                    logger.error(f"Failed to deliver message to {to_username}: {e}")
                    # If delivery fails, make sure message is stored
                    self.storage.add_message(to_username, from_username, content)
            else:
                # Store message for offline user or if not PRIMARY
                self.storage.add_message(to_username, from_username, content)
        
        elif update_type == "DELETE_MESSAGES":
            username = data["username"]
            msg_ids = data["msg_ids"]
            self.storage.delete_messages(username, msg_ids)
    
    def handle_client(self, client: socket.socket, address):
        """Handle client connection"""
        logger.info(f"Connection from {address}")
        
        # Check if we're PRIMARY before accepting clients
        if self.storage.get_server_state() != "PRIMARY" or self.transitioning:
            logger.warning(f"Rejecting client {address} - not PRIMARY or in transition")
            try:
                # Send notification to client
                notification = Message(cmd="server_status", body="Server unavailable, please try another server", error=True)
                encoded = self.protocol.encode(notification)
                client.send(len(encoded).to_bytes(4, 'big'))
                client.send(encoded)
            except:
                pass
            client.close()
            return
        
        try:
            username = None
            
            while self.running:
                # Re-check server state before processing each message
                if self.storage.get_server_state() != "PRIMARY" or self.transitioning:
                    logger.warning(f"Server no longer PRIMARY or in transition, closing connection to {address}")
                    # Send notification to client
                    try:
                        error_msg = Message(cmd="server_status", body="Server is no longer available, please reconnect", error=True)
                        encoded = self.protocol.encode(error_msg)
                        client.send(len(encoded).to_bytes(4, 'big'))
                        client.send(encoded)
                    except:
                        pass
                    break
                
                length_bytes = client.recv(4)
                if not length_bytes:
                    break
                msg_length = int.from_bytes(length_bytes, 'big')
                data = client.recv(msg_length)
                
                message = self.protocol.decode(data)
                cmd = message.cmd
                username = message.src
                response = None
                
                # Check server state again before processing command
                if self.storage.get_server_state() != "PRIMARY" or self.transitioning:
                    response = Message(cmd=cmd, body="Server is in transition, please try again later", error=True)
                else:
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
            logger.error(f"Error in handling client: {e}")
        finally:
            # Clean up connection
            if username and username in self.current_users:
                self.current_users.pop(username)
            client.close()
            logger.info(f"Connection closed: {address}")

    def start(self):
        """Start the server"""
        # Start replication first
        self.replication.start()
        
        # Connect to peer servers
        for peer_id, peer_host, peer_port in self.peer_servers:
            self.replication.connect_to_peer(peer_id, peer_host, peer_port)
        
        # Start main server
        self.server.listen()
        logger.info(f"Server running on {self.host}:{self.port}, replication on port {self.replication_port}")
        
        # Handle graceful shutdown
        def sigterm_handler(_signo, _stack_frame):
            logger.info("Received shutdown signal")
            self.running = False
            self.server.close()
            self.replication.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, sigterm_handler)
        signal.signal(signal.SIGINT, sigterm_handler)
        
        try:
            # Accept client connections if PRIMARY
            while self.running:
                try:
                    # Only accept connections if primary
                    if self.storage.get_server_state() == "PRIMARY":
                        client, address = self.server.accept()
                        thread = threading.Thread(target=self.handle_client, args=(client, address))
                        thread.daemon = True
                        thread.start()
                    else:
                        # Sleep briefly to avoid busy waiting
                        time.sleep(0.1)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        logger.error(f"Error accepting client: {e}")
                        time.sleep(0.1)
        finally:
            self.running = False
            self.server.close()
            self.replication.stop()
            logger.info("Server stopped")
    
    def handle_create(self, username: str, message: Message, client: socket.socket):
        """Handle account creation"""
        if self.storage.user_exists(username):
            response = Message(cmd="create", body="Username already exists", error=True)
        else:
            # Save user to storage
            self.storage.add_user(username, message.body)
            # Update in-memory users
            self.users[username] = message.body
            # Add to current users
            self.current_users[username] = client
            
            # Replicate to backups if we're PRIMARY
            if self.storage.get_server_state() == "PRIMARY":
                self.replication.broadcast_data_update("ADD_USER", {
                    "username": username,
                    "password": message.body
                })
                # Wait for acknowledgment from majority
                self.replication.wait_for_acks()
            
            response = Message(cmd="create", body="Account created", to=username)
        return response
    
    def handle_login(self, username: str, message: Message, client: socket.socket):
        """Handle user login"""
        if not self.storage.user_exists(username):
            response = Message(cmd="login", body="Username/Password error", error=True)
        elif self.users[username] != message.body:
            response = Message(cmd="login", body="Username/Password error", error=True)
        else:
            self.current_users[username] = client
            # Check for unread messages
            messages = self.storage.get_messages(username)
            unread_count = len(messages)
            response = Message(cmd="login", body=f"Login successful. You have {unread_count} unread messages.", to=username)
        return response
    
    def handle_logoff(self, username: str, message: Message):
        """Handle user logout"""
        if username in self.current_users:
            self.current_users.pop(username)
            response = Message(cmd="logoff", body="Logged out successfully")
        return response

    def handle_list(self, message: Message):
        """Handle listing users"""
        pattern = message.body if message.body else "all"
        matching_users = []
        for user in self.users.keys():
            if pattern == "all" or pattern in user:
                matching_users.append(user)
        response = Message(cmd="list", body=",".join(matching_users))
        return response

    def handle_send(self, username: str, message: Message):
        """Handle sending a message"""
        recipient = message.to
        content = message.body
        
        if not content or not recipient:
            response = Message(cmd="send", body="Message content and recipient are required", error=True)
        elif not self.storage.user_exists(recipient):
            response = Message(cmd="send", body="Recipient not found", error=True)
        else:
            try:
                # Generate a new message ID
                msg_id = str(uuid.uuid4())
                
                # Get current server state
                server_state = self.storage.get_server_state()
                
                # Check if server is in transition
                if self.transitioning:
                    return Message(cmd="send", body="Server is in transition, please try again later", error=True)
                
                # Replicate to backups if PRIMARY
                if server_state == "PRIMARY":
                    self.replication.broadcast_data_update("ADD_MESSAGE", {
                        "to": recipient,
                        "from": username,
                        "content": content,
                        "msg_id": msg_id
                    })
                    # Wait for acknowledgment
                    self.replication.wait_for_acks()
                
                    # Only attempt delivery if PRIMARY
                    if recipient in self.current_users:
                        # Deliver immediately if recipient is online
                        try:
                            client = self.current_users[recipient]
                            notification = Message(cmd="deliver", src=username, body=content, msg_ids=[msg_id])
                            encoded = self.protocol.encode(notification)
                            client.send(len(encoded).to_bytes(4, 'big'))
                            client.send(encoded)
                            logger.info(f"Message from {username} delivered to {recipient}")
                        except Exception as e:
                            logger.error(f"Failed to deliver message to {recipient}: {e}")
                            # Store message if delivery fails
                            self.storage.add_message(recipient, username, content)
                    else:
                        # Store message for offline recipient
                        self.storage.add_message(recipient, username, content)
                        logger.info(f"Message from {username} stored for offline user {recipient}")
                    
                    response = Message(cmd="send", body="Message sent successfully")
                else:
                    # Not PRIMARY, cannot send messages
                    response = Message(cmd="send", body=f"Cannot send messages, server is in {server_state} state", error=True)
            except Exception as e:
                logger.error(f"Error in handle_send: {e}")
                response = Message(cmd="send", body="Failed to send message", error=True)
        
        return response
    
    def handle_deliver(self, username: str, message: Message, client: socket.socket):
        """Handle message delivery request"""
        if not self.storage.user_exists(username):
            return Message(cmd="deliver", body="User not found", error=True)
        
        # Check if server is in PRIMARY state before processing
        server_state = self.storage.get_server_state()
        if server_state != "PRIMARY":
            return Message(cmd="deliver", body=f"Cannot deliver messages, server is in {server_state} state", error=True)
            
        # Check if server is in transition
        if self.transitioning:
            return Message(cmd="deliver", body="Server is in transition, please try again later", error=True)
        
        # Get messages for user
        messages = self.storage.get_messages(username)
        
        # Track which messages this client has already seen
        if not hasattr(self, 'client_seen_messages'):
            self.client_seen_messages = {}
        
        if username not in self.client_seen_messages:
            self.client_seen_messages[username] = set()
            
        # Filter out already seen messages
        unseen_messages = []
        for msg in messages:
            msg_id = msg[0]
            if msg_id not in self.client_seen_messages[username]:
                unseen_messages.append(msg)
                # Add to seen set when limit=0 (preserving messages)
                if message.limit == 0:
                    self.client_seen_messages[username].add(msg_id)
        
        # Apply limit if specified
        limit = message.limit if message.limit > 0 else len(unseen_messages)
        messages_to_send = unseen_messages[:limit]
        
        # Send messages
        for msg_id, sender, content in messages_to_send:
            notification = Message(cmd="deliver", src=sender, body=content, msg_ids=[msg_id])
            encoded = self.protocol.encode(notification)
            client.send(len(encoded).to_bytes(4, 'big'))
            client.send(encoded)
        
        # Only remove delivered messages if a limit was specified
        # This ensures chat history is preserved unless explicitly requested
        if message.limit > 0:
            # Double-check we're still PRIMARY and not transitioning before deletion
            if self.storage.get_server_state() != "PRIMARY" or self.transitioning:
                # If state changed during processing, don't delete messages
                return Message(cmd="deliver", body=f"Delivered {len(messages_to_send)} messages, but server state changed - messages preserved")
                
            # Remove delivered messages from storage
            msg_ids = [msg[0] for msg in messages_to_send]
            if msg_ids:
                # Add to seen set for positive limits too
                for msg_id in msg_ids:
                    self.client_seen_messages[username].add(msg_id)
                    
                # Replicate deletion to backups
                self.replication.broadcast_data_update("DELETE_MESSAGES", {
                    "username": username,
                    "msg_ids": msg_ids
                })
                # Wait for acknowledgment
                self.replication.wait_for_acks()
                
                # Delete local copies
                self.storage.delete_messages(username, msg_ids)
        
        # Return success response
        return Message(cmd="deliver", body=f"Delivered {len(messages_to_send)} messages")
    
    def handle_delete_messages(self, username: str, message: Message):
        """Handle message deletion request"""
        if not message.msg_ids:
            return Message(cmd="delete_msgs", body="No message IDs provided", error=True)
        
        try:
            # Only allow deletion if PRIMARY and not transitioning
            if self.storage.get_server_state() != "PRIMARY":
                return Message(cmd="delete_msgs", body="Cannot delete messages, server is not PRIMARY", error=True)
                
            if self.transitioning:
                return Message(cmd="delete_msgs", body="Server is in transition, please try again later", error=True)
                
            # Replicate deletion to backups
            self.replication.broadcast_data_update("DELETE_MESSAGES", {
                "username": username,
                "msg_ids": message.msg_ids
            })
            # Wait for acknowledgment
            self.replication.wait_for_acks()
            
            # Final check before actual deletion
            if self.storage.get_server_state() != "PRIMARY" or self.transitioning:
                return Message(cmd="delete_msgs", body="Server state changed during processing, messages preserved", error=True)
                
            # Delete messages locally
            self.storage.delete_messages(username, message.msg_ids)
            
            return Message(cmd="delete_msgs", body="Messages deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting messages: {e}")
            return Message(cmd="delete_msgs", body="Failed to delete messages", error=True)
    
    def handle_delete(self, username: str, message: Message):
        """Handle account deletion"""
        if not self.storage.user_exists(username):
            response = Message(cmd="delete", body="User does not exist", error=True)
        elif self.transitioning:
            response = Message(cmd="delete", body="Server is in transition, please try again later", error=True)
        elif self.storage.get_server_state() != "PRIMARY":
            response = Message(cmd="delete", body="Cannot delete account, server is not PRIMARY", error=True)
        else:
            # Delete user
            self.storage.delete_user(username)
            
            # Update in-memory state
            if username in self.users:
                self.users.pop(username)
            if username in self.current_users:
                self.current_users.pop(username)
            
            # Double-check we're still PRIMARY before replication
            if self.storage.get_server_state() == "PRIMARY" and not self.transitioning:
                self.replication.broadcast_data_update("DELETE_USER", {
                    "username": username
                })
                # Wait for acknowledgment
                self.replication.wait_for_acks()
            
            response = Message(cmd="delete", body="Account deleted")
        
        return response

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat Server')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--replication_port', type=int, default=5500, help='Port for replication')
    parser.add_argument('--data_dir', default='./data', help='Data directory')
    parser.add_argument('--peers', default='', help='Comma-separated list of peer servers in format: id,host,port;id2,host2,port2')
    parser.add_argument('--custom_mode', action='store_true', help='Use custom binary protocol')
    parser.add_argument('--primary', action='store_true', help='Start as primary server')
    
    args = parser.parse_args()
    
    # Parse peer servers
    peer_servers = []
    if args.peers:
        for peer in args.peers.split(';'):
            parts = peer.split(',')
            if len(parts) == 3:
                peer_id, host, port = parts
                peer_servers.append((peer_id, host, int(port)))
    
    # Create data directory if it doesn't exist
    os.makedirs(args.data_dir, exist_ok=True)
    
    # Initialize server
    server = ChatServer(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        replication_port=args.replication_port,
        peer_servers=peer_servers,
        custom_mode=args.custom_mode
    )
    
    # Set initial state if specified
    if args.primary:
        server.storage.set_server_state("PRIMARY")
    
    # Start server
    server.start()