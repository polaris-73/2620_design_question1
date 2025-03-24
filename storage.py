import json
import os
import time
import threading
from typing import Dict, List, Tuple, Optional, Any
import uuid
import shutil

class Storage:
    """Handles persistence of users, messages, and server state"""
    
    def __init__(self, data_dir: str):
        """
        Initialize the storage system
        data_dir: directory to store data files
        """
        self.data_dir = data_dir
        self.users_file = os.path.join(data_dir, "users.txt")
        self.state_file = os.path.join(data_dir, "server_state.txt")
        self.log_file = os.path.join(data_dir, "log.txt")
        self.lock = threading.RLock()
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize empty data structures if files don't exist
        if not os.path.exists(self.users_file):
            self._write_users({})
        
        if not os.path.exists(self.state_file):
            self._write_state("BACKUP")  # Default to backup role

    def _write_log(self, operation: str, data: Any) -> None:
        """Write an operation to the write-ahead log"""
        with self.lock:
            with open(self.log_file, "a") as f:
                log_entry = {
                    "timestamp": time.time(),
                    "operation": operation,
                    "data": data
                }
                f.write(json.dumps(log_entry) + "\n")
    
    def _write_users(self, users: Dict[str, str]) -> None:
        """Write users dictionary to file"""
        with self.lock:
            with open(self.users_file, "w") as f:
                json.dump(users, f)
    
    def _read_users(self) -> Dict[str, str]:
        """Read users dictionary from file"""
        with self.lock:
            try:
                with open(self.users_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}
    
    def _write_state(self, state: str) -> None:
        """Write server state to file"""
        with self.lock:
            with open(self.state_file, "w") as f:
                f.write(state)
    
    def _read_state(self) -> str:
        """Read server state from file"""
        with self.lock:
            try:
                with open(self.state_file, "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return "BACKUP"
    
    def _get_message_file(self, username: str) -> str:
        """Get the path to a user's message file"""
        return os.path.join(self.data_dir, f"messages_{username}.txt")
    
    def _write_messages(self, username: str, messages: List[Tuple[str, str, str]]) -> None:
        """Write a user's messages to file"""
        with self.lock:
            with open(self._get_message_file(username), "w") as f:
                json.dump(messages, f)
    
    def _read_messages(self, username: str) -> List[Tuple[str, str, str]]:
        """Read a user's messages from file"""
        with self.lock:
            try:
                with open(self._get_message_file(username), "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return []
    
    def get_users(self) -> Dict[str, str]:
        """Get all user accounts"""
        return self._read_users()
    
    def user_exists(self, username: str) -> bool:
        """Check if a user exists"""
        users = self._read_users()
        return username in users
    
    def add_user(self, username: str, password: str) -> None:
        """Add a new user"""
        with self.lock:
            users = self._read_users()
            users[username] = password
            self._write_log("ADD_USER", {"username": username, "password": password})
            self._write_users(users)
    
    def delete_user(self, username: str) -> None:
        """Delete a user and their messages"""
        with self.lock:
            # Delete user from users file
            users = self._read_users()
            if username in users:
                del users[username]
                self._write_log("DELETE_USER", {"username": username})
                self._write_users(users)
            
            # Delete user's message file
            message_file = self._get_message_file(username)
            if os.path.exists(message_file):
                os.remove(message_file)
            
            # Also remove any messages sent by this user to others
            for user in users:
                messages = self._read_messages(user)
                filtered_msgs = [msg for msg in messages if msg[1] != username]
                if len(filtered_msgs) != len(messages):
                    self._write_messages(user, filtered_msgs)
    
    def get_messages(self, username: str) -> List[Tuple[str, str, str]]:
        """Get all messages for a user"""
        return self._read_messages(username)
    
    def add_message(self, to_username: str, from_username: str, content: str) -> str:
        """Add a message to a user's queue, returns message ID"""
        with self.lock:
            msg_id = str(uuid.uuid4())
            messages = self._read_messages(to_username)
            messages.append((msg_id, from_username, content))
            self._write_log("ADD_MESSAGE", {
                "to": to_username, 
                "from": from_username, 
                "content": content,
                "msg_id": msg_id
            })
            self._write_messages(to_username, messages)
            return msg_id
    
    def delete_messages(self, username: str, msg_ids: List[str]) -> None:
        """Delete specific messages for a user"""
        with self.lock:
            messages = self._read_messages(username)
            filtered_msgs = [msg for msg in messages if msg[0] not in msg_ids]
            if len(filtered_msgs) != len(messages):
                self._write_log("DELETE_MESSAGES", {
                    "username": username,
                    "msg_ids": msg_ids
                })
                self._write_messages(username, filtered_msgs)
    
    def remove_messages(self, username: str, count: int) -> List[Tuple[str, str, str]]:
        """Remove and return a number of messages from a user's queue"""
        with self.lock:
            messages = self._read_messages(username)
            to_return = messages[:count]
            remaining = messages[count:]
            self._write_log("REMOVE_MESSAGES", {
                "username": username,
                "count": count,
                "msg_ids": [msg[0] for msg in to_return]
            })
            self._write_messages(username, remaining)
            return to_return
    
    def set_server_state(self, state: str) -> None:
        """Set the server state (PRIMARY or BACKUP)"""
        self._write_log("SET_STATE", {"state": state})
        self._write_state(state)
    
    def get_server_state(self) -> str:
        """Get the current server state"""
        return self._read_state()
    
    def backup(self, target_dir: str) -> None:
        """Create a backup of all data files"""
        with self.lock:
            os.makedirs(target_dir, exist_ok=True)
            
            # Copy users file
            if os.path.exists(self.users_file):
                shutil.copy2(self.users_file, os.path.join(target_dir, "users.txt"))
            
            # Copy state file
            if os.path.exists(self.state_file):
                shutil.copy2(self.state_file, os.path.join(target_dir, "server_state.txt"))
            
            # Copy log file
            if os.path.exists(self.log_file):
                shutil.copy2(self.log_file, os.path.join(target_dir, "log.txt"))
            
            # Copy all message files
            for filename in os.listdir(self.data_dir):
                if filename.startswith("messages_"):
                    src_path = os.path.join(self.data_dir, filename)
                    dst_path = os.path.join(target_dir, filename)
                    shutil.copy2(src_path, dst_path)
    
    def restore(self, source_dir: str) -> None:
        """Restore data from backup directory"""
        with self.lock:
            # Copy users file
            src_users = os.path.join(source_dir, "users.txt")
            if os.path.exists(src_users):
                shutil.copy2(src_users, self.users_file)
            
            # Copy state file
            src_state = os.path.join(source_dir, "server_state.txt")
            if os.path.exists(src_state):
                shutil.copy2(src_state, self.state_file)
            
            # Copy log file
            src_log = os.path.join(source_dir, "log.txt")
            if os.path.exists(src_log):
                shutil.copy2(src_log, self.log_file)
            
            # Copy all message files
            for filename in os.listdir(source_dir):
                if filename.startswith("messages_"):
                    src_path = os.path.join(source_dir, filename)
                    dst_path = os.path.join(self.data_dir, filename)
                    shutil.copy2(src_path, dst_path) 