import unittest
import os
import sys
import time
import json
import shutil
import subprocess
import threading
import socket
import uuid
import signal
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("fault_tolerance_tests")

# Add parent directory to path so we can import from there
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import Message, JSONProtocol
from replication import ReplicationClient

class TestPersistenceFaultTolerance(unittest.TestCase):
    """Tests for persistence and fault tolerance in the chat system."""
    
    @classmethod
    def setUpClass(cls):
        # Create test data directories
        cls.data_dirs = ["./test_data1", "./test_data2", "./test_data3"]
        for data_dir in cls.data_dirs:
            if os.path.exists(data_dir):
                shutil.rmtree(data_dir)
            os.makedirs(data_dir)
            
        # Server ports configuration - use higher port numbers to avoid conflicts
        cls.server_ports = [6100, 6200, 6300]
        cls.replication_ports = [6150, 6250, 6350]
        cls.server_processes = []
        
        # Ensure no lingering server processes
        cls._kill_existing_servers()
    
    @classmethod
    def _kill_existing_servers(cls):
        """Kill any existing server processes that might interfere with tests"""
        if sys.platform == "win32":
            os.system('taskkill /f /im python.exe 2>nul')
        else:
            os.system('pkill -f "python.*server.py" || true')
        time.sleep(1)  # Give processes time to terminate
        
    @classmethod
    def tearDownClass(cls):
        # Kill all server processes
        for process in cls.server_processes:
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass
                    
        # Clean up test data directories
        for data_dir in cls.data_dirs:
            if os.path.exists(data_dir):
                shutil.rmtree(data_dir)
    
    def setUp(self):
        # Kill any running servers
        self.stop_all_servers()
        
        # Clear server processes list
        self.__class__.server_processes = []
        
        # Start all servers for each test
        self.start_all_servers()
        
        # Wait for servers to initialize and elect a primary
        logger.info("Waiting for servers to initialize...")
        time.sleep(5)  # Increased wait time
    
    def tearDown(self):
        # Stop all servers after each test
        self.stop_all_servers()
    
    def start_server(self, index, primary=False):
        """Start a server with the given index"""
        data_dir = self.__class__.data_dirs[index]
        server_port = self.__class__.server_ports[index]
        replication_port = self.__class__.replication_ports[index]
        
        # Build peer list
        peers = []
        for i in range(len(self.__class__.data_dirs)):
            if i != index:
                peer_dir = self.__class__.data_dirs[i]
                peer_host = "localhost"
                peer_rep_port = self.__class__.replication_ports[i]
                peers.append(f"{peer_dir},{peer_host},{peer_rep_port}")
        peers_arg = ";".join(peers)
        
        # Build command
        cmd = [
            sys.executable, 
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py"),
            "--host", "localhost",
            "--port", str(server_port),
            "--replication_port", str(replication_port),
            "--data_dir", data_dir,
            "--peers", peers_arg
        ]
        
        if primary:
            cmd.append("--primary")
        
        # Start the server
        logger.info(f"Starting server {index} on port {server_port} (replication port {replication_port})")
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        self.__class__.server_processes.append(process)
        return process
    
    def start_all_servers(self):
        """Start all three servers with the first as primary"""
        logger.info("Starting all servers...")
        for i in range(len(self.__class__.data_dirs)):
            is_primary = (i == 0)  # First server is primary
            self.start_server(i, primary=is_primary)
        
        # Give servers time to start up
        time.sleep(2)
    
    def stop_all_servers(self):
        """Stop all running servers"""
        logger.info("Stopping all servers...")
        for process in self.__class__.server_processes:
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass
        self.__class__.server_processes = []
        
        # Make sure all servers are stopped
        self.__class__._kill_existing_servers()
    
    def get_client(self):
        """Get a client connected to the servers"""
        logger.info("Creating client connection to servers...")
        server_list = [("localhost", port) for port in self.__class__.server_ports]
        client = ReplicationClient(server_list)
        
        # Ensure connection
        if not client.connect():
            logger.warning("Initial connection failed, retrying...")
            time.sleep(1)
            client.connect()
            
        return client
    
    def create_user(self, client, username, password):
        """Create a user account"""
        logger.info(f"Creating user: {username}")
        msg = Message(cmd="create", src=username, body=password)
        client.send_msg(msg)
        
        # Wait for response
        response = None
        for _ in range(30):  # Increased retries with longer timeout
            response = client.receive_msg()
            if response and response.cmd == "create":
                logger.info(f"User creation response: {'success' if not response.error else 'error - ' + response.body}")
                break
            time.sleep(0.2)  # Slightly longer wait
        
        if not response:
            logger.error(f"No response received for user creation: {username}")
            return False
            
        return response and not response.error
    
    def login_user(self, client, username, password):
        """Login with the given credentials"""
        logger.info(f"Logging in user: {username}")
        msg = Message(cmd="login", src=username, body=password)
        client.send_msg(msg)
        
        # Wait for response
        response = None
        for _ in range(30):  # Increased retries
            response = client.receive_msg()
            if response and response.cmd == "login":
                logger.info(f"Login response: {'success' if not response.error else 'error - ' + response.body}")
                break
            time.sleep(0.2)
        
        return response and not response.error
    
    def send_message(self, client, sender, recipient, content):
        """Send a message"""
        logger.info(f"Sending message from {sender} to {recipient}: {content}")
        msg = Message(cmd="send", src=sender, to=recipient, body=content)
        client.send_msg(msg)
        
        # Wait for response
        response = None
        for _ in range(30):  # Increased retries
            response = client.receive_msg()
            if response and response.cmd == "send":
                logger.info(f"Send message response: {'success' if not response.error else 'error - ' + response.body}")
                break
            time.sleep(0.2)
        
        return response and not response.error
    
    def get_messages(self, client, username, limit=0):
        """Retrieve messages without deleting them"""
        logger.info(f"Getting messages for user: {username} (limit={limit})")
        msg = Message(cmd="deliver", src=username, limit=limit)
        client.send_msg(msg)
        
        # Collect all messages
        messages = []
        delivery_completed = False
        for _ in range(40):  # Increased retries
            response = client.receive_msg()
            if response:
                if response.cmd == "deliver" and not response.error:
                    if hasattr(response, 'msg_ids') and response.msg_ids:
                        messages.append((response.src, response.body, response.msg_ids[0]))
                        logger.info(f"Received message from {response.src}: {response.body}")
                elif response.cmd == "deliver" and "Delivered" in response.body:
                    # End of messages
                    delivery_completed = True
                    logger.info(f"Message delivery complete: {response.body}")
                    break
            time.sleep(0.2)
        
        if not delivery_completed:
            logger.warning(f"Message delivery may not have completed for {username}")
            
        return messages
    
    def test_persistence_across_restart(self):
        """Test that messages persist when servers are restarted"""
        logger.info("\n===== STARTING TEST: Persistence Across Restart =====")
        # Create test users
        client = self.get_client()
        self.assertTrue(self.create_user(client, "alice", "password1"))
        
        # Make a new client connection to ensure we're getting fresh responses
        client = self.get_client()
        self.assertTrue(self.create_user(client, "bob", "password2"))
        
        # Send messages
        client = self.get_client()
        self.assertTrue(self.login_user(client, "alice", "password1"))
        self.assertTrue(self.send_message(client, "alice", "bob", "Hello Bob!"))
        self.assertTrue(self.send_message(client, "alice", "bob", "How are you?"))
        
        # Stop all servers
        logger.info("Stopping all servers before restart test...")
        self.stop_all_servers()
        
        # Restart servers
        logger.info("Restarting all servers...")
        self.start_all_servers()
        time.sleep(5)  # Allow servers to initialize
        
        # Login as Bob and check messages
        client = self.get_client()
        self.assertTrue(self.login_user(client, "bob", "password2"))
        
        messages = self.get_messages(client, "bob")
        self.assertEqual(len(messages), 2)
        
        # Verify message content
        sources = [msg[0] for msg in messages]
        contents = [msg[1] for msg in messages]
        
        self.assertIn("alice", sources)
        self.assertIn("Hello Bob!", contents)
        self.assertIn("How are you?", contents)
  
    
    
    def test_server_restart_join_existing_cluster(self):
        """Test that a restarted server can join the existing cluster and sync data"""
        logger.info("\n===== STARTING TEST: Server Restart and Join =====")
        # Create test users
        client = self.get_client()
        self.assertTrue(self.create_user(client, "user7", "password7"))
        
        client = self.get_client()
        self.assertTrue(self.create_user(client, "user8", "password8"))
        
        # Stop one server (index 2)
        logger.info("Stopping server 2...")
        self.__class__.server_processes[2].terminate()
        self.__class__.server_processes[2].wait(timeout=2)
        del self.__class__.server_processes[2]
        
        # Send messages while server 2 is down
        client = self.get_client()
        self.assertTrue(self.login_user(client, "user7", "password7"))
        self.assertTrue(self.send_message(client, "user7", "user8", "While server was down"))
        
        # Restart server 2
        logger.info("Restarting server 2...")
        self.start_server(2)
        
        # Wait for sync to complete
        logger.info("Waiting for sync to complete...")
        time.sleep(7)
        
        # Kill the remaining original servers
        logger.info("Killing other servers...")
        for _ in range(2):
            self.__class__.server_processes[0].terminate()
            self.__class__.server_processes[0].wait(timeout=2)
            del self.__class__.server_processes[0]
            time.sleep(2)
        
        # Wait for server 2 to become primary
        logger.info("Waiting for server 2 to become primary...")
        time.sleep(7)
        
        # Verify that server 2 has the message sent while it was down
        client = self.get_client()
        self.assertTrue(self.login_user(client, "user8", "password8"))
        
        messages = self.get_messages(client, "user8")
        self.assertGreaterEqual(len(messages), 1)
        
        contents = [msg[1] for msg in messages]
        self.assertIn("While server was down", contents)
    
   


if __name__ == "__main__":
    unittest.main()