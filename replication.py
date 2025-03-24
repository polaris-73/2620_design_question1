import socket
import threading
import json
import time
import queue
from typing import Dict, List, Tuple, Optional, Callable, Any
import logging
import os
from protocol import JSONProtocol, Message
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("replication")

class ReplicationProtocol:
    """Protocol for server-to-server communication"""
    
    @staticmethod
    def encode_message(cmd: str, data: Any) -> bytes:
        """Encode a replication message"""
        message = {
            "cmd": cmd,
            "data": data,
            "timestamp": time.time()
        }
        json_str = json.dumps(message)
        return json_str.encode()
    
    @staticmethod
    def decode_message(data: bytes) -> Tuple[str, Any, float]:
        """Decode a replication message"""
        message = json.loads(data.decode())
        return (message["cmd"], message["data"], message["timestamp"])


class ReplicationServer:
    """Server that handles replication between chat servers"""
    
    def __init__(self, host: str, port: int, data_dir: str, 
                 on_state_change: Callable[[str], None],
                 on_data_update: Callable[[str, Any], None]):
        """
        Initialize replication server
        host: hostname to bind to
        port: port to bind to (should be different from chat server port)
        data_dir: directory to store data
        on_state_change: callback for state changes
        on_data_update: callback for data updates
        """
        self.host = host
        self.port = port
        self.data_dir = data_dir
        self.on_state_change = on_state_change
        self.on_data_update = on_data_update
        
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((host, port))
        
        self.is_running = False
        self.state = "BACKUP"  # Default state
        self.transitioning = False  # Flag to indicate server is transitioning between states
        self.peers = {}  # Dict of peer_id -> (host, port)
        self.peer_connections = {}  # Dict of peer_id -> socket
        self.backups = []  # List of backup peers
        
        self.heartbeat_interval = 1.0  # Seconds
        self.election_timeout = 5.0  # Seconds
        self.missed_heartbeats = 0
        self.max_missed_heartbeats = 3
        
        self.last_heartbeat = time.time()  # Initialize to current time
        self.election_timer = None  # Timer for election timeout
        
        # Message queues
        self.outgoing_queue = queue.Queue()
        
        # Election lock to prevent concurrent elections
        self.election_lock = threading.Lock()
        
        # Threads
        self.listener_thread = None
        self.sender_thread = None
        self.heartbeat_thread = None
        self.monitor_thread = None
        self.sync_thread = None
        
        # Data sync status
        self.last_sync_time = 0
        self.sync_interval = 60.0  # Sync data every 60 seconds
    
    def start(self):
        """Start the replication server"""
        if self.is_running:
            return
        
        self.is_running = True
        self.server.listen(10)
        
        # Start threads
        self.listener_thread = threading.Thread(target=self._listener_loop)
        self.listener_thread.daemon = True
        self.listener_thread.start()
        
        self.sender_thread = threading.Thread(target=self._sender_loop)
        self.sender_thread.daemon = True
        self.sender_thread.start()
        
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info(f"Replication server started on {self.host}:{self.port}")
    
    def stop(self):
        """Stop the replication server"""
        self.is_running = False
        if self.election_timer:
            self.election_timer.cancel()
        
        # Close all connections
        for conn in self.peer_connections.values():
            try:
                conn.close()
            except:
                pass
        
        try:
            self.server.close()
        except:
            pass
        
        logger.info("Replication server stopped")
    
    def _listener_loop(self):
        """Listen for incoming connections"""
        while self.is_running:
            try:
                client, address = self.server.accept()
                threading.Thread(target=self._handle_peer, args=(client, address)).start()
            except Exception as e:
                if self.is_running:
                    logger.error(f"Error accepting connection: {e}")
                    time.sleep(0.1)
    
    def _handle_peer(self, client: socket.socket, address: Tuple[str, int]):
        """Handle a peer connection"""
        peer_id = None
        
        try:
            # First message should be a HELLO with peer_id
            length_bytes = client.recv(4)
            if not length_bytes:
                return
            
            msg_length = int.from_bytes(length_bytes, 'big')
            data = client.recv(msg_length)
            
            cmd, msg_data, _ = ReplicationProtocol.decode_message(data)
            
            if cmd != "HELLO":
                logger.warning(f"Expected HELLO message, got {cmd}")
                client.close()
                return
            
            peer_id = msg_data["peer_id"]
            logger.info(f"New peer connection from {peer_id} at {address}")
            
            # Send our own HELLO
            response = ReplicationProtocol.encode_message("HELLO", {
                "peer_id": self.data_dir,
                "state": self.state
            })
            client.send(len(response).to_bytes(4, 'big'))
            client.send(response)
            
            # Add to peer connections
            self.peer_connections[peer_id] = client
            self.peers[peer_id] = address
            
            # If we're primary, add to backups
            if self.state == "PRIMARY":
                self.backups.append(peer_id)
                # Initiate data sync with the new backup
                self._handle_sync_request(peer_id, client)
            
            # Main message loop
            while self.is_running:
                length_bytes = client.recv(4)
                if not length_bytes:
                    break
                
                msg_length = int.from_bytes(length_bytes, 'big')
                data = client.recv(msg_length)
                
                cmd, msg_data, timestamp = ReplicationProtocol.decode_message(data)
                if self.transitioning:
                    continue
                
                if cmd == "HEARTBEAT":
                    self.last_heartbeat = time.time()
                    # Reset election timeout
                    if self.election_timer:
                        self.election_timer.cancel()
                    self.election_timer = threading.Timer(self.election_timeout, self._start_election)
                    self.election_timer.daemon = True
                    self.election_timer.start()
                
                elif cmd == "STATE_CHANGE":
                    new_state = msg_data["state"]
                    logger.info(f"Peer {peer_id} changed state to {new_state}")
                    
                    if new_state == "PRIMARY" and self.state == "PRIMARY":
                        # Conflict resolution - highest peer_id wins
                        if peer_id > self.data_dir:
                            logger.info(f"Conflict resolution: stepping down to BACKUP")
                            self._become_backup()
                    
                    # If peer became primary and we're backup, update our primary
                    if new_state == "PRIMARY" and self.state == "BACKUP":
                        # Remove peer from backups if it was there
                        if peer_id in self.backups:
                            self.backups.remove(peer_id)
                
                elif cmd == "ELECTION":
                    # If we have a higher ID, we start our own election
                    if peer_id < self.data_dir:
                        logger.info(f"Got ELECTION from {peer_id}, starting our own election")
                        self._start_election()
                    else:
                        logger.info(f"Got ELECTION from {peer_id}, acknowledging")
                        # Send acknowledgment
                        ack = ReplicationProtocol.encode_message("ELECTION_ACK", {})
                        client.send(len(ack).to_bytes(4, 'big'))
                        client.send(ack)
                
                elif cmd == "ELECTED":
                    # Peer has been elected as primary
                    logger.info(f"Peer {peer_id} has been elected as PRIMARY")
                    if self.state == "PRIMARY":
                        logger.info(f"Stepping down to BACKUP")
                        self._become_backup()
                    
                    # Reset election timeout
                    if self.election_timer:
                        self.election_timer.cancel()
                    self.election_timer = threading.Timer(self.election_timeout, self._start_election)
                    self.election_timer.daemon = True
                    self.election_timer.start()
                
                elif cmd == "DATA_UPDATE":
                    # Update our data
                    op_type = msg_data["type"]
                    op_data = msg_data["data"]
                    logger.debug(f"Data update: {op_type}")
                    self.on_data_update(op_type, op_data)
                
                elif cmd == "SYNC_REQUEST":
                    # Primary is requesting we send our data directory for backup
                    logger.info(f"Received sync request from {peer_id}")
                    self._handle_sync_request(peer_id, client)
                    
                elif cmd == "SYNC_DATA":
                    # Process synchronized data
                    data_type = msg_data["type"]
                    data = msg_data["data"]
                    logger.info(f"Received sync data of type: {data_type}")
                    self._handle_sync_data(data_type, data)
                    
                elif cmd == "SYNC_COMPLETE":
                    logger.info(f"Sync with {peer_id} completed")
                    self.last_sync_time = time.time()
        
        except Exception as e:
            logger.error(f"Error handling peer {peer_id}: {e}")
        finally:
            try:
                client.close()
            except:
                pass
            
            if peer_id and peer_id in self.peer_connections:
                del self.peer_connections[peer_id]
            
            if peer_id and peer_id in self.peers:
                del self.peers[peer_id]
            
            if peer_id and peer_id in self.backups:
                self.backups.remove(peer_id)
            
            logger.info(f"Peer connection closed: {peer_id}")
    
    def _sender_loop(self):
        """Process outgoing messages"""
        while self.is_running:
            try:
                peer_id, message = self.outgoing_queue.get(timeout=0.1)
                
                if peer_id == "ALL":
                    # Send to all peers
                    for pid, conn in self.peer_connections.items():
                        try:
                            conn.send(len(message).to_bytes(4, 'big'))
                            conn.send(message)
                        except Exception as e:
                            logger.error(f"Error sending to peer {pid}: {e}")
                else:
                    # Send to specific peer
                    if peer_id in self.peer_connections:
                        try:
                            conn = self.peer_connections[peer_id]
                            conn.send(len(message).to_bytes(4, 'big'))
                            conn.send(message)
                        except Exception as e:
                            logger.error(f"Error sending to peer {peer_id}: {e}")
                
                self.outgoing_queue.task_done()
            
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Error in sender loop: {e}")
                time.sleep(0.1)
    
    def _heartbeat_loop(self):
        """Send heartbeats if we're the PRIMARY"""
        while self.is_running:
            try:
                if self.state == "PRIMARY":
                    heartbeat = ReplicationProtocol.encode_message("HEARTBEAT", {
                        "timestamp": time.time()
                    })
                    self.outgoing_queue.put(("ALL", heartbeat))
                
                time.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
    
    def _start_election(self):
        """Start an election to become the primary"""
        with self.election_lock:
            if self.state == "PRIMARY":
                # We're already primary
                return
            
            # Don't start a new election if we're already a candidate
            if self.state == "CANDIDATE":
                return
            
            logger.info("Starting election...")
            self.state = "CANDIDATE"
            self.on_state_change("CANDIDATE")
            
            # Send ELECTION message to all peers
            election_msg = ReplicationProtocol.encode_message("ELECTION", {
                "peer_id": self.data_dir
            })
            self.outgoing_queue.put(("ALL", election_msg))
            
            # Wait for a short time for responses
            time.sleep(1.0)
            
            # If no one objects, become primary
            # Only become primary if we're still a candidate
            if self.state == "CANDIDATE":
                self._become_primary()
    
    def _become_primary(self):
        """Become the primary server"""
        logger.info("Becoming PRIMARY")
        
        # Set transitioning flag to prevent message processing during state change
        self.transitioning = True
        
        # Change state and notify handler
        self.state = "PRIMARY"
        self.on_state_change("PRIMARY")
        
        # Notify all peers
        elected_msg = ReplicationProtocol.encode_message("ELECTED", {
            "peer_id": self.data_dir
        })
        self.outgoing_queue.put(("ALL", elected_msg))
        
        # Update backups list
        self.backups = list(self.peer_connections.keys())
        
        # Request data synchronization from any existing peers
        # This ensures we have the latest data if we're becoming primary after a failover
        self._request_data_sync()
        
        # Allow time for data sync to be requested
        time.sleep(1.0)
        
        # Reset transitioning flag after state change is complete
        self.transitioning = False
        logger.info("PRIMARY transition complete, ready for client connections")
    
    def _become_backup(self):
        """Become a backup server"""
        logger.info("Becoming BACKUP")
        
        # Set transitioning flag to prevent message processing during state change
        self.transitioning = True
        
        # Change state and notify handler
        self.state = "BACKUP"
        self.on_state_change("BACKUP")
        
        # Notify all peers
        state_msg = ReplicationProtocol.encode_message("STATE_CHANGE", {
            "state": "BACKUP"
        })
        self.outgoing_queue.put(("ALL", state_msg))
        
        # Reset transitioning flag after state change is complete
        self.transitioning = False
        logger.info("BACKUP transition complete")
    
    def connect_to_peer(self, peer_id: str, host: str, port: int):
        """Connect to a peer server"""
        if peer_id in self.peer_connections:
            return
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            
            # Send HELLO
            hello = ReplicationProtocol.encode_message("HELLO", {
                "peer_id": self.data_dir,
                "state": self.state
            })
            sock.send(len(hello).to_bytes(4, 'big'))
            sock.send(hello)
            
            # Start handler
            threading.Thread(target=self._handle_peer, args=(sock, (host, port))).start()
            
            logger.info(f"Connected to peer {peer_id} at {host}:{port}")
            return True
        
        except Exception as e:
            logger.error(f"Error connecting to peer {peer_id}: {e}")
            return False
    
    def broadcast_data_update(self, update_type: str, data: Any):
        """Broadcast a data update to all backups"""
        if self.state != "PRIMARY":
            return
        
        update_msg = ReplicationProtocol.encode_message("DATA_UPDATE", {
            "type": update_type,
            "data": data
        })
        
        self.outgoing_queue.put(("ALL", update_msg))
    
    def wait_for_acks(self, timeout: float = 1.0) -> bool:
        """Wait for acknowledgments from a majority of backups"""
        # In a real implementation, you'd wait for specific ACKs
        # For simplicity, we'll just wait for a short time
        time.sleep(timeout)
        
        # Need majority of nodes (including self)
        total_nodes = len(self.backups) + 1
        majority = (total_nodes // 2) + 1
        
        # We count as 1 ack (self)
        # For single-node operation, we need at least 1 ack (ourself)
        return 1 >= majority or total_nodes <= 1

    def _monitor_loop(self):
        """Monitor for primary server failures"""
        while self.is_running:
            try:
                if self.state == "BACKUP":
                    # Check if we've missed too many heartbeats from primary
                    current_time = time.time()
                    if current_time - self.last_heartbeat > self.heartbeat_interval * 2:
                        self.missed_heartbeats += 1
                        logger.info(f"Missed heartbeat #{self.missed_heartbeats} from primary")
                        
                        # After several missed heartbeats, start election
                        if self.missed_heartbeats >= self.max_missed_heartbeats:
                            logger.warning(f"Primary seems to be down after {self.missed_heartbeats} missed heartbeats")
                            self._start_election()
                    else:
                        # Reset counter if we received a heartbeat
                        if self.missed_heartbeats > 0:
                            logger.info("Heartbeat received, resetting counter")
                            self.missed_heartbeats = 0
                
                # If we're primary, periodically sync with backups
                elif self.state == "PRIMARY":
                    current_time = time.time()
                    if current_time - self.last_sync_time > self.sync_interval and self.backups:
                        # Initiate sync with all backups
                        for backup_id in self.backups:
                            if backup_id in self.peer_connections:
                                backup_client = self.peer_connections[backup_id]
                                self._handle_sync_request(backup_id, backup_client)
                        self.last_sync_time = current_time
                
                # Sleep for a portion of the heartbeat interval
                time.sleep(self.heartbeat_interval / 2)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(0.1)

    def _request_data_sync(self):
        """Request data synchronization from peers"""
        if not self.peer_connections:
            logger.info("No peers to request data sync from")
            return
            
        sync_request = ReplicationProtocol.encode_message("SYNC_REQUEST", {
            "timestamp": time.time()
        })
        
        # Request sync from the first connected peer
        peer_id = next(iter(self.peer_connections.keys()))
        logger.info(f"Requesting data sync from peer {peer_id}")
        self.outgoing_queue.put((peer_id, sync_request))

    def _handle_sync_request(self, peer_id, client):
        """Handle a sync request from a peer"""
        logger.info(f"Received sync request from {peer_id}")
        
        # Send all users
        users_data = self._get_users_data()
        sync_users = ReplicationProtocol.encode_message("SYNC_DATA", {
            "type": "USERS",
            "data": users_data
        })
        client.send(len(sync_users).to_bytes(4, 'big'))
        client.send(sync_users)
        
        # Send all messages for each user
        messages_data = self._get_messages_data()
        sync_messages = ReplicationProtocol.encode_message("SYNC_DATA", {
            "type": "MESSAGES",
            "data": messages_data
        })
        client.send(len(sync_messages).to_bytes(4, 'big'))
        client.send(sync_messages)
        
        # Send sync complete notification
        sync_complete = ReplicationProtocol.encode_message("SYNC_COMPLETE", {
            "timestamp": time.time()
        })
        client.send(len(sync_complete).to_bytes(4, 'big'))
        client.send(sync_complete)
        
    def _get_users_data(self):
        """Get all user data for synchronization"""
        from storage import Storage
        storage = Storage(self.data_dir)
        return storage.get_users()
        
    def _get_messages_data(self):
        """Get all message data for synchronization"""
        from storage import Storage
        storage = Storage(self.data_dir)
        users = storage.get_users()
        
        messages_data = {}
        for username in users:
            messages_data[username] = storage.get_messages(username)
            
        return messages_data

    def _handle_sync_data(self, data_type, data):
        """Handle synced data from another peer"""
        logger.info(f"Processing synced data of type: {data_type}")
        
        from storage import Storage
        storage = Storage(self.data_dir)
        
        if data_type == "USERS":
            # Update user data
            users = data
            for username, password in users.items():
                if not storage.user_exists(username):
                    storage.add_user(username, password)
                    self.on_data_update("ADD_USER", {
                        "username": username,
                        "password": password
                    })
                    
        elif data_type == "MESSAGES":
            # Update message data
            messages_data = data
            for username, messages in messages_data.items():
                existing_messages = storage.get_messages(username)
                existing_msg_ids = [msg[0] for msg in existing_messages]
                
                for msg in messages:
                    msg_id, from_username, content = msg
                    if msg_id not in existing_msg_ids:
                        storage.add_message(username, from_username, content)
                        self.on_data_update("ADD_MESSAGE", {
                            "to": username,
                            "from": from_username,
                            "content": content,
                            "msg_id": msg_id
                        })


class ReplicationClient:
    """Client that connects to multiple chat servers with failover"""
    
    def __init__(self, server_list: List[Tuple[str, int]], custom_mode: bool = False):
        """
        Initialize the replication client
        server_list: List of (host, port) tuples for chat servers
        custom_mode: Whether to use custom binary protocol
        """
        self.server_list = server_list
        self.custom_mode = custom_mode
        self.protocol = JSONProtocol if not custom_mode else CustomProtocol
        self.current_server_idx = 0
        self.socket = None
        self.connected = False
        self.connection_lock = threading.RLock()
        
        self.message_queue = queue.Queue()  # Queue for messages during reconnection
        self.last_reconnect_attempt = 0
        self.reconnect_backoff = 1.0  # Starting backoff time in seconds
        self.max_reconnect_backoff = 30.0  # Maximum backoff time
        
        # Add session tracking for reconnections
        self.session_id = str(uuid.uuid4())
        self.current_username = None
    
    def connect(self) -> bool:
        """Connect to the current server"""
        with self.connection_lock:
            if self.connected:
                return True
            
            current_time = time.time()
            if current_time - self.last_reconnect_attempt < self.reconnect_backoff:
                return False
            
            self.last_reconnect_attempt = current_time
            
            # Try all servers in a round-robin fashion
            for _ in range(len(self.server_list)):
                try:
                    host, port = self.server_list[self.current_server_idx]
                    logger.info(f"Attempting to connect to {host}:{port}...")
                    
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.settimeout(3.0)  # Set a timeout for connection
                    self.socket.connect((host, port))
                    self.socket.settimeout(None)  # Reset timeout for normal operation
                    
                    self.connected = True
                    self.reconnect_backoff = 1.0  # Reset backoff time
                    logger.info(f"Connected to server {host}:{port}")
                    
                    # Process any queued messages
                    self._process_queued_messages()
                    
                    return True
                except Exception as e:
                    logger.warning(f"Failed to connect to {host}:{port}: {e}")
                    self.socket = None
                    
                    # Try next server
                    self.current_server_idx = (self.current_server_idx + 1) % len(self.server_list)
            
            # If we get here, we failed to connect to any server
            self.connected = False
            # Increase backoff time
            self.reconnect_backoff = min(self.reconnect_backoff * 2, self.max_reconnect_backoff)
            return False
    
    def _process_queued_messages(self):
        """Process any messages in the queue"""
        try:
            while not self.message_queue.empty():
                message = self.message_queue.get_nowait()
                try:
                    data = self.protocol.encode(message)
                    self.socket.send(len(data).to_bytes(4, 'big'))
                    self.socket.send(data)
                    logger.info(f"Sent queued message: {message.cmd}")
                except Exception as e:
                    logger.error(f"Failed to send queued message: {e}")
                    # Put message back in queue
                    self.message_queue.put(message)
                    raise e  # Re-raise to break out of loop
                self.message_queue.task_done()
        except Exception:
            # If any error occurs, we'll retry later
            pass
    
    def close(self):
        """Close the connection"""
        with self.connection_lock:
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            self.connected = False
    
    def send_msg(self, msg: Message) -> bool:
        """Send a message to the server"""
        with self.connection_lock:
            # Track username for reconnection
            if msg.cmd == "login" and not msg.error:
                self.current_username = msg.src
                
            if not self.connected:
                # Queue message for later
                logger.info(f"Queuing message for later delivery: {msg.cmd}")
                self.message_queue.put(msg)
                # Try to reconnect
                self.connect()
                return False
            
            try:
                # Add session ID to message for tracking
                if not hasattr(msg, 'session_id'):
                    msg.session_id = self.session_id
                
                data = self.protocol.encode(msg)
                self.socket.send(len(data).to_bytes(4, 'big'))
                self.socket.send(data)
                logger.debug(f"Message sent: {msg.cmd}")
                return True
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                self.connected = False
                self.socket = None
                
                # Queue message for later
                logger.info(f"Queuing message after error: {msg.cmd}")
                self.message_queue.put(msg)
                
                # Try to reconnect
                self.connect()
                return False
    
    def receive_msg(self) -> Optional[Message]:
        """Receive a message from the server"""
        with self.connection_lock:
            if not self.connected:
                if not self.connect():
                    return None
            
            try:
                if self.socket:
                    self.socket.settimeout(0.1)  # Short timeout for polling
                    try:
                        length_bytes = self.socket.recv(4)
                        if not length_bytes:
                            logger.warning("Connection closed by server (empty length)")
                            self.connected = False
                            self.socket = None
                            return None
                        
                        msg_length = int.from_bytes(length_bytes, 'big')
                        data = self.socket.recv(msg_length)
                        
                        if not data:
                            logger.warning("Connection closed by server (empty data)")
                            self.connected = False
                            self.socket = None
                            return None
                        
                        return self.protocol.decode(data)
                    except socket.timeout:
                        # This is normal in polling mode
                        return None
                    finally:
                        if self.socket:
                            self.socket.settimeout(None)  # Reset timeout
                else:
                    return None
            
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                self.connected = False
                self.socket = None
                return None 