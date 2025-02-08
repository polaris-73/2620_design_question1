import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import threading
import os
import sys
import argparse
import signal
from datetime import datetime
from protocol import Message, JSONProtocol, CustomProtocol

class ChatClientGUI:
    def __init__(self, host, port, custom_mode=False):
        self.host = host
        self.port = port
        self.proto = JSONProtocol if not custom_mode else CustomProtocol
        self.socket = None
        self.username = None
        self.running = True
        self.receive_thread = None
    
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
        
        # Connecting to server
        try:
            self.connect()
        except Exception as e:
            raise Exception(f"Connection failed: {str(e)}")

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

        self.chat_display = scrolledtext.ScrolledText(left_frame, wrap=tk.WORD, height=20)
        self.chat_display.pack()
        
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
        self.users_listbox.pack()
        
        # Control buttons
        ttk.Button(right_frame, text="Refresh Users", command=self.refresh_users).pack()
        ttk.Button(right_frame, text="Read Messages", command=self.read_messages).pack()
        ttk.Button(right_frame, text="Delete Account", command=self.handle_delete_account).pack()
        ttk.Button(right_frame, text="Logout", command=self.handle_logout).pack()

    def connect(self):
        # Connect to server, end when server is end
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self.receive_thread = threading.Thread(target=self.listen_for_msgs)
        self.receive_thread.daemon = True
        self.receive_thread.start()

    def send_msg(self, msg):
        try:
            data = self.proto.encode(msg)
            self.socket.send(len(data).to_bytes(4, 'big'))
            self.socket.send(data)
        except Exception as err:
            messagebox.showerror("Error", f"Failed to send message: {str(err)}")
            self.running = False

    def listen_for_msgs(self):
        while self.running:
            try:
                length_bytes = self.socket.recv(4)
                if not length_bytes:
                    break
                msg_length = int.from_bytes(length_bytes, 'big')
                data = self.socket.recv(msg_length)
                # import pdb; pdb.set_trace()
                if not data:
                    break
                msg = self.proto.decode(data)
                # Schedule GUI updates in main thread
                self.root.after(0, self.handle_msg, msg)
            except Exception as err:
                self.running = False
                break

    def handle_msg(self, msg):
        if msg.cmd == "login":
            if msg.error:
                messagebox.showerror("Login Failed", msg.body)
            else:
                self.username = msg.to
                messagebox.showinfo("Success", msg.body)
                self.notebook.tab(1, state='normal')
                self.notebook.select(1)
                self.refresh_users()
        
        elif msg.cmd == "deliver":
            self.chat_display.insert(tk.END, f"[{msg.src}: {msg.body}\n")
            self.chat_display.see(tk.END)
        
        elif msg.cmd == "create":
            if msg.error:
                messagebox.showerror("Account Creation Failed", msg.body)
            else:
                self.username = msg.to
                messagebox.showinfo("Success", "Account created successfully!")
                self.notebook.tab(1, state='normal')
                self.notebook.select(1)
                self.refresh_users()
        
        elif msg.cmd == "delete":
            if msg.error:
                messagebox.showerror("Delete Failed", msg.body)
            else:
                messagebox.showinfo("Success", msg.body)
                self.username = None
                self.notebook.tab(1, state='disabled')
                self.notebook.select(0)
        
        elif msg.cmd == "list":
            self.users_listbox.delete(0, tk.END)
            users = msg.body.split(",")
            for user in users:
                if user and user != self.username:
                    self.users_listbox.insert(tk.END, user)
        
        elif msg.cmd == "logoff":
            messagebox.showinfo("Logged Out", msg.body)
            self.username = None
            self.notebook.tab(1, state='disabled')
            self.notebook.select(0)

    def handle_login(self):
        user = self.username_entry.get()
        pwd = self.password_entry.get()
        if not user or not pwd:
            messagebox.showerror("Error", "Please enter both username and password")
            return
        m = Message(cmd="login", src=user, body=(pwd))
        self.send_msg(m)
        self.password_entry.delete(0, tk.END)

    def handle_create_account(self):
        user = self.username_entry.get()
        pwd = self.password_entry.get()
        if not user or not pwd:
            messagebox.showerror("Error", "Please enter both username and password")
            return
        m = Message(cmd="create", src=user, body=(pwd))
        self.send_msg(m)
        self.password_entry.delete(0, tk.END)

    def send_chat_message(self):
        recipient = self.users_listbox.get(tk.ACTIVE)
        if not recipient:
            messagebox.showerror("Error", "Please select a recipient")
            return
        content = self.msg_entry.get()
        if not content:
            return
        m = Message(cmd="send", src=self.username, to=recipient, body=content)
        self.send_msg(m)
        
        # Add message to chat display
        self.chat_display.insert(tk.END, f"[{self.username} -> {recipient}: {content}\n")
        self.chat_display.see(tk.END)
        self.msg_entry.delete(0, tk.END)

    def refresh_users(self):
        m = Message(cmd="list", body="all")
        self.send_msg(m)

    def read_messages(self):
        m = Message(cmd="deliver", src=self.username)
        self.send_msg(m)

    def handle_delete_account(self):
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete your account?"):
            m = Message(cmd="delete", src=self.username)
            self.send_msg(m)

    def handle_logout(self):         
        m = Message(cmd="logoff", src=self.username)
        self.send_msg(m)

    def filter_users(self):
        filter_text = self.filter_entry.get()
        if not filter_text:
            self.refresh_users()  # If filter is empty, show all users
        else:
            m = Message(cmd="list", body=filter_text)
            self.send_msg(m)

    def run(self):
        self.root.mainloop()

def main():
    parser = argparse.ArgumentParser(description="Chat Client GUI")
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--custom_mode', action='store_true')
    
    args = parser.parse_args()
    
    client = ChatClientGUI(args.host, args.port, args.custom_mode)
    try:
        client.run()
    except Exception as err:
        print("Error:", err)

if __name__ == "__main__":
    main() 