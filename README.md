# Persistent and Fault-Tolerant Chat Application

A client-server chat application with persistence and 2-fault tolerance, implemented in Python.

## Features

- Multiple concurrent client connections
- GUI-based client interface using tkinter
- User authentication (login/create account)
- Real-time messaging between online users
- Message queueing for offline users
- Support for both JSON and custom binary wire protocols
- User management (create account, delete account, logout)
- List of online users
- Message history
- **Persistence** - system can be stopped and restarted without losing data
- **2-Fault Tolerance** - system can survive up to 2 server failures

## Requirements

- Python 3.7+
- tkinter (usually comes with Python)

## Installation

```bash
# Install requirements
pip install -r requirements.txt
```

## Running the Fault-Tolerant System

### Starting Multiple Server Instances

You'll need at least 3 servers for 2-fault tolerance. Start each server in a different terminal:

#### Server 1 (Primary)
```bash
python server.py --host localhost --port 5000 --replication_port 5500 --data_dir ./data1 --primary
```

#### Server 2 (Backup)
```bash
python server.py --host localhost --port 5001 --replication_port 5501 --data_dir ./data2 --peers "data1,localhost,5500"
```

#### Server 3 (Backup)
```bash
python server.py --host localhost --port 5002 --replication_port 5502 --data_dir ./data3 --peers "data1,localhost,5500;data2,localhost,5501"
```

### Starting the Client

```bash
# Connect to all servers for automatic failover
python client.py --servers "localhost:5000,localhost:5001,localhost:5002"

# Or connect to a single server
python client.py --host localhost --port 5000
```

## Testing Fault Tolerance

1. Start all three servers as shown above
2. Connect a client to the system
3. Create an account or log in
4. Send a few messages
5. Kill the primary server (Ctrl+C in its terminal)
6. Observe that one of the backup servers becomes the new primary
7. The client should reconnect automatically
8. Verify that all messages are still available

## Protocol Design

### JSON Protocol
Messages are encoded as JSON objects with the following fields:
- `cmd`: Command type (login, create, send, etc.)
- `src`: Source username
- `to`: Destination username
- `body`: Message content
- `error`: Error flag

### Custom Binary Protocol
A more efficient binary protocol with the following format:
```
[1 byte: cmd length][cmd bytes]
[1 byte: src length][src bytes]
[1 byte: to length][to bytes]
[2 bytes: body length][body bytes]
[1 byte: error]
```

## Features

### User Management
- Create account
- Login/Logout
- Delete account
- View online users

### Messaging
- Send messages to online users
- Queue messages for offline users
- Read message history
- Real-time message delivery

## Fault-Tolerance Design

The system implements a primary-backup replication model:

1. **Server Roles**:
   - PRIMARY: Handles client connections and replicates state to backups
   - BACKUP: Receives updates from primary, ready to take over if primary fails
   - CANDIDATE: Transitional state during leader election

2. **Data Persistence**:
   - All user accounts and messages are stored on disk
   - Each server has its own persistent storage
   - Data is synchronized between servers

3. **Failure Detection**:
   - Heartbeats between servers detect failures
   - If primary fails, backups hold election to choose new primary

4. **Client Reconnection**:
   - Clients maintain list of all servers
   - Automatic reconnection to available servers on failure
   - Messages are queued during reconnection attempts

## Security
- Passwords are hashed using SHA-256
- No plaintext password storage
- Session management for multiple clients

## Running on Multiple Machines

To run the system across multiple machines, you'll need to adjust the host parameters:

1. On machine 1:
```bash
python server.py --host 0.0.0.0 --port 5000 --replication_port 5500 --data_dir ./data1 --primary
```

2. On machine 2:
```bash
python server.py --host 0.0.0.0 --port 5000 --replication_port 5500 --data_dir ./data2 --peers "data1,machine1_ip,5500"
```

3. On machine 3:
```bash
python server.py --host 0.0.0.0 --port 5000 --replication_port 5500 --data_dir ./data3 --peers "data1,machine1_ip,5500;data2,machine2_ip,5500"
```

4. For clients:
```bash
python client.py --servers "machine1_ip:5000,machine2_ip:5000,machine3_ip:5000"
```