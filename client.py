import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import threading
import os
import sys
import argparse
import signal
import time
import uuid
import logging
import queue
from datetime import datetime
from protocol import Message, JSONProtocol, CustomProtocol
from replication import ReplicationClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("client")

class ChatClientGUI:
    def __init__(self, server_list, custom_mode=False):
        self.server_list = server_list
        self.custom_mode = custom_mode
        self.proto = JSONProtocol if not custom_mode else CustomProtocol
        self.username = None
        self.running = True
        self.receive_thread = None
        self.message_ids = {}  
        
        # Create the replication client for fault tolerance
        self.repl_client = ReplicationClient(server_list, custom_mode)
    
        self.root = tk.Tk()
        self.root.title("Chat Bot Client!")
        
        # Setup ttk gui
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack()
        self.login_frame = ttk.Frame(self.notebook)
        self.chat_frame = ttk.Frame(self.notebook)
        
        self.notebook.add(self.login_frame, text='Login')
        self.notebook.add(self.chat_frame, text='Chat')
        self.setup_login_page()
        
        self.setup_chat_page()
        
        # Disable chat tab initially
        self.notebook.tab(1, state='disabled')
        
        # Add status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Disconnected")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Connecting to server
        try:
            if self.repl_client.connect():
                self.status_var.set(f"Connected to server")
            else:
                self.status_var.set("Failed to connect, will retry...")
        except Exception as e:
            self.status_var.set(f"Connection failed: {str(e)}")
        
        # Start receiver thread
        self.receive_thread = threading.Thread(target=self.listen_for_msgs)
        self.receive_thread.daemon = True
        self.receive_thread.start()

    def setup_login_page(self):
        # Login frame
        login_container = ttk.LabelFrame(self.login_frame, text="Login")
        login_container.pack()
        
        # Username
        ttk.Label(login_container, text="Username:").pack(pady=5)
        self.username_entry = ttk.Entry(login_container)
        self.username_entry.pack()

        # Password
        ttk.Label(login_container, text="Password:").pack(pady=5)
        self.password_entry = ttk.Entry(login_container, show="*")
        self.password_entry.pack()
        
        # Buttons
        button_frame = ttk.Frame(login_container)
        button_frame.pack()
        
        ttk.Button(button_frame, text="Login", command=self.handle_login).pack()
        ttk.Button(button_frame, text="Create Account", command=self.handle_create_account).pack()

    def setup_chat_page(self):
        # Chat interface on left side
        self.chat_frame.columnconfigure(0, weight=7)
        self.chat_frame.columnconfigure(1, weight=3)
        self.chat_frame.rowconfigure(0, weight=1)
        left_frame = ttk.Frame(self.chat_frame)
        left_frame.grid()

        # Message display frame
        msg_frame = ttk.Frame(left_frame)
        msg_frame.pack(fill='both', expand=True)

        # Chat display with message selection
        self.chat_display = scrolledtext.ScrolledText(msg_frame, wrap=tk.WORD, height=20)
        self.chat_display.pack(side=tk.LEFT, fill='both', expand=True)
        
        # Message selection listbox
        self.msg_select = tk.Listbox(msg_frame, width=3, selectmode=tk.MULTIPLE)
        self.msg_select.pack(side=tk.RIGHT, fill='y')
        
        # Message input area
        input_frame = ttk.Frame(left_frame)
        input_frame.pack(fill='x')
        
        self.msg_entry = ttk.Entry(input_frame)
        self.msg_entry.pack()
        
        ttk.Button(input_frame, text="Send", command=self.send_chat_message).pack(side=tk.RIGHT)
        # Right side - Users and controls
        right_frame = ttk.Frame(self.chat_frame)
        right_frame.grid(row=0, column=1)
        
        # User filter
        filter_frame = ttk.Frame(right_frame)
        filter_frame.pack()
        ttk.Label(filter_frame, text="Filter Users:").pack(side=tk.LEFT)
        self.filter_entry = ttk.Entry(filter_frame)
        self.filter_entry.pack(side=tk.LEFT, fill='x', expand=True)
        ttk.Button(filter_frame, text="Filter", command=self.filter_users).pack(side=tk.RIGHT)
        
        # Users list
        ttk.Label(right_frame, text="Online Users:").pack()
        self.users_listbox = tk.Listbox(right_frame, height=10)
        self.users_listbox.pack(fill='both', expand=True)
        
        # Message controls
        message_controls = ttk.Frame(right_frame)
        message_controls.pack(fill='x', pady=5)
        
        ttk.Label(message_controls, text="Messages to read:").pack(side=tk.LEFT)
        self.msg_limit = ttk.Spinbox(message_controls, from_=1, to=100, width=5)
        self.msg_limit.pack(side=tk.LEFT, padx=5)
        self.msg_limit.set(10)  
        
        ttk.Button(message_controls, text="Read Messages", command=self.read_messages).pack(side=tk.LEFT, padx=5)
        ttk.Button(message_controls, text="Delete Selected", command=self.delete_messages).pack(side=tk.LEFT)
        
        # Control buttons
        ttk.Button(right_frame, text="Refresh Users", command=self.refresh_users).pack(fill='x', pady=2)
        ttk.Button(right_frame, text="Delete Account", command=self.handle_delete_account).pack(fill='x', pady=2)
        ttk.Button(right_frame, text="Logout", command=self.handle_logout).pack(fill='x', pady=2)

    def send_msg(self, msg):
        """Send a message using the replication client"""
        try:
            if self.repl_client.send_msg(msg):
                return True
            else:
                # Message is queued for later delivery
                self.status_var.set("Message queued for delivery, attempting reconnection...")
                return False
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send message: {str(e)}")
            self.status_var.set(f"Error: {str(e)}")
            return False

    def listen_for_msgs(self):
        reconnect_delay = 1.0  # Initial reconnect delay in seconds
        password_cache = {}    # Cache for auto-relogin
        
        while self.running:
            if not self.repl_client.connected:
                try:
                    if self.repl_client.connect():
                        self.status_var.set("Reconnected to server")
                        
                        # If we were logged in, relogin automatically
                        if self.username and self.username in password_cache:
                            relogin_msg = Message(cmd="login", src=self.username, 
                                               body=password_cache[self.username])
                            self.send_msg(relogin_msg)
                            
                            # After successful reconnection and relogin, request message history
                            self.root.after(1000, self.refresh_history)
                    else:
                        # Failed to reconnect, wait before retrying
                        time.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 1.5, 10.0)  # Exponential backoff up to 10 seconds
                except Exception as e:
                    logger.error(f"Error during reconnection: {e}")
                    time.sleep(1.0)
            
            try:
                # Try to receive a message
                msg = self.repl_client.receive_msg()
                if msg:
                    # For login/create success, cache password for potential reconnection
                    if (msg.cmd == "login" or msg.cmd == "create") and not msg.error:
                        if self.password_entry.get():  # Only cache if we have a password
                            password_cache[msg.to] = self.password_entry.get()
                            # Clear password field for security
                            self.password_entry.delete(0, tk.END)
                    
                    # Process the message in the main thread
                    self.root.after(0, self.handle_msg, msg)
                else:
                    # No message received or error occurred
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                time.sleep(0.1)
                
    def refresh_history(self):
        """Refresh message history after reconnection"""
        if self.username:
            # Clear the current chat display to prevent duplicates
            self.chat_display.configure(state='normal')
            self.chat_display.delete(1.0, tk.END)
            self.chat_display.configure(state='disabled')
            
            # Clear the message selection list and IDs
            self.msg_select.delete(0, tk.END)
            self.message_ids.clear()
            
            # Request message history without removing messages (use limit=0)
            # This will get all unread messages from the server
            msg = Message(cmd="deliver", src=self.username, limit=0)
            self.send_msg(msg)
            
            # Show a status message
            self.status_var.set("Refreshing message history...")

    def handle_msg(self, msg):
        """Handle received messages"""
        try:
            # Special handler for server status messages
            if msg.cmd == "server_status":
                # Server has reported a status change or error
                self.status_var.set(msg.body)
                messagebox.showwarning("Server Status", msg.body)
                
                # If server is reporting it's no longer available, force reconnect
                if "no longer" in msg.body or "transition" in msg.body:
                    logger.info("Server reported state change, initiating reconnection")
                    # Close current connection and try next server
                    self.repl_client.connection_lock.acquire()
                    try:
                        if self.repl_client.socket:
                            self.repl_client.close()
                        # Move to next server
                        self.repl_client.current_server_idx = (self.repl_client.current_server_idx + 1) % len(self.repl_client.server_list)
                        # Reset the last reconnect attempt to try immediately
                        self.repl_client.last_reconnect_attempt = 0
                    finally:
                        self.repl_client.connection_lock.release()
                return
            
            # Handle received message
            if msg.cmd == "deliver":
                # Update the chat display
                self.chat_display.configure(state='normal')
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Store message ID for potential deletion
                if msg.msg_ids and len(msg.msg_ids) > 0:
                    msg_id = msg.msg_ids[0]
                    idx = len(self.msg_select.get(0, tk.END))
                    self.message_ids[idx] = msg_id
                    self.msg_select.insert(tk.END, idx + 1)
                
                self.chat_display.insert(tk.END, f"[{timestamp}] {msg.src}: {msg.body}\n")
                self.chat_display.configure(state='disabled')
                self.chat_display.see(tk.END)
            
            # Other handlers remain the same as in the original code
            elif msg.cmd == "create":
                if not msg.error:
                    messagebox.showinfo("Success", "Account created successfully!")
                    self.username = msg.to
                    self.notebook.tab(1, state='normal')
                    self.notebook.select(1)
                    self.refresh_users()
                else:
                    messagebox.showerror("Error", msg.body)
            
            elif msg.cmd == "login":
                if not msg.error:
                    messagebox.showinfo("Success", msg.body)
                    self.username = msg.to
                    self.notebook.tab(1, state='normal')
                    self.notebook.select(1)
                    self.refresh_users()
                else:
                    messagebox.showerror("Error", msg.body)
            
            elif msg.cmd == "list":
                # Update the users list
                self.users_listbox.delete(0, tk.END)
                if msg.body:
                    for user in msg.body.split(','):
                        if user and user != self.username:
                            self.users_listbox.insert(tk.END, user)
            
            elif msg.cmd == "send":
                if msg.error:
                    messagebox.showerror("Error", msg.body)
                    # If server is in transition, wait a moment and retry
                    if "transition" in msg.body:
                        self.status_var.set("Server in transition, waiting to retry...")
                        # Try to reconnect after a delay
                        self.root.after(2000, self.try_reconnect)
            
            elif msg.cmd == "delete":
                if not msg.error:
                    messagebox.showinfo("Success", "Account deleted successfully!")
                    self.notebook.tab(1, state='disabled')
                    self.notebook.select(0)
                    self.username = None
                else:
                    messagebox.showerror("Error", msg.body)
            
            elif msg.cmd == "delete_msgs":
                if not msg.error:
                    # Clear selected messages
                    self.msg_select.selection_clear(0, tk.END)
                else:
                    messagebox.showerror("Error", msg.body)
                    
            elif msg.cmd == "logoff":
                if not msg.error:
                    self.username = None
                    self.notebook.tab(1, state='disabled')
                    self.notebook.select(0)
                    messagebox.showinfo("Success", "Logged out successfully")
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def handle_login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required!")
            return
        
        msg = Message(cmd="login", src=username, body=password)
        self.send_msg(msg)

    def handle_create_account(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required!")
            return
        
        msg = Message(cmd="create", src=username, body=password)
        self.send_msg(msg)

    def send_chat_message(self):
        if not self.username:
            messagebox.showerror("Error", "You need to be logged in to send messages!")
            return
        
        recipient = self.users_listbox.get(tk.ACTIVE)
        message_text = self.msg_entry.get()
        
        if not recipient:
            messagebox.showerror("Error", "Select a recipient from the user list!")
            return
        
        if not message_text:
            messagebox.showerror("Error", "Message cannot be empty!")
            return
        
        # Send message to server
        msg = Message(cmd="send", src=self.username, to=recipient, body=message_text)
        
        if self.send_msg(msg):
            # Clear message input on successful send
            self.msg_entry.delete(0, tk.END)
            
            # Add message to our own display
            self.chat_display.configure(state='normal')
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.chat_display.insert(tk.END, f"[{timestamp}] You -> {recipient}: {message_text}\n")
            self.chat_display.configure(state='disabled')
            self.chat_display.see(tk.END)

    def refresh_users(self):
        """Refresh user list"""
        if self.username:
            msg = Message(cmd="list", src=self.username, body="all")
            self.send_msg(msg)
            # Also refresh message history
            self.refresh_history()

    def read_messages(self):
        try:
            limit = int(self.msg_limit.get())
        except ValueError:
            limit = 10
        
        # Set limit to 0 to read messages without deleting them (preserve history)
        msg = Message(cmd="deliver", src=self.username, limit=0)
        if self.send_msg(msg):
            # Show success toast
            self.status_var.set("Reading message history...")

    def delete_messages(self):
        selected_indices = self.msg_select.curselection()
        
        if not selected_indices:
            messagebox.showinfo("Info", "No messages selected for deletion!")
            return
        
        msg_ids = []
        for idx in selected_indices:
            if idx in self.message_ids:
                msg_ids.append(self.message_ids[idx])
        
        if msg_ids:
            # Remove selected messages from display
            for idx in selected_indices[::-1]:  # Delete from end to avoid index shifts
                self.msg_select.delete(idx)
                if idx in self.message_ids:
                    del self.message_ids[idx]
            
            # Update message indices
            new_message_ids = {}
            for i, idx in enumerate(self.msg_select.get(0, tk.END)):
                if int(idx) - 1 in self.message_ids:
                    new_message_ids[i] = self.message_ids[int(idx) - 1]
            self.message_ids = new_message_ids
            
            # Send delete request
            msg = Message(cmd="delete_msgs", src=self.username, msg_ids=msg_ids)
            self.send_msg(msg)
            
            # Update chat display
            self.chat_display.configure(state='normal')
            self.chat_display.delete(1.0, tk.END)
            self.chat_display.configure(state='disabled')

    def handle_delete_account(self):
        if not self.username:
            return
        
        if messagebox.askyesno("Confirm", "Are you sure you want to delete your account? This cannot be undone!"):
            msg = Message(cmd="delete", src=self.username)
            self.send_msg(msg)

    def handle_logout(self):         
        if self.username:
            msg = Message(cmd="logoff", src=self.username)
            self.send_msg(msg)
            self.notebook.tab(1, state='disabled')
            self.notebook.select(0)
            self.username = None

    def filter_users(self):
        pattern = self.filter_entry.get()
        msg = Message(cmd="list", src=self.username, body=pattern)
        self.send_msg(msg)

    def try_reconnect(self):
        """Force a reconnection attempt"""
        logger.info("Attempting reconnection...")
        self.status_var.set("Reconnecting...")
        
        # Close current connection
        self.repl_client.close()
        
        # Try to connect
        if self.repl_client.connect():
            self.status_var.set("Reconnected successfully")
            # If we have username/password, try to relogin
            if self.username and self.username in password_cache:
                relogin_msg = Message(cmd="login", src=self.username, 
                                   body=password_cache[self.username])
                self.send_msg(relogin_msg)
        else:
            self.status_var.set("Reconnection failed, will retry automatically")

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.handle_close)
        self.root.mainloop()
    
    def handle_close(self):
        """Handle window close event"""
        self.running = False
        if self.username:
            # Try to log off
            try:
                msg = Message(cmd="logoff", src=self.username)
                self.send_msg(msg)
            except:
                pass
        
        # Close client connection
        self.repl_client.close()
        
        # Destroy window
        self.root.destroy()

def main():
    parser = argparse.ArgumentParser(description='Chat Client')
    parser.add_argument('--host', default=os.environ.get('SERVER_HOST', 'localhost'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('SERVER_PORT', '5000')))
    parser.add_argument('--custom_mode', action='store_true')
    parser.add_argument('--servers', default='', 
                        help='Comma-separated list of server addresses in format: host1:port1,host2:port2')
    
    args = parser.parse_args()
    
    # Parse server list
    server_list = []
    if args.servers:
        for server in args.servers.split(','):
            parts = server.split(':')
            if len(parts) == 2:
                host, port = parts
                server_list.append((host, int(port)))
    
    # If no servers specified, use the host/port arguments
    if not server_list:
        server_list = [(args.host, args.port)]
    
    try:
        client = ChatClientGUI(server_list, args.custom_mode)
        client.run()
    except Exception as e:
        print(f"Error starting client: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()