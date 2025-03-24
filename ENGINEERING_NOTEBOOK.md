# Engineering Notebook

## Original Protocol Comparison

### JSON Protocol
Messages are encoded as JSON objects with the following fields:
- `cmd`: Command type (login, create, send, etc.)
- `src`: Source username
- `to`: Destination username
- `body`: Message content
- `error`: Error flag

### Custom Binary Protocol
```
[1 byte: cmd length][cmd bytes]
[1 byte: src length][src bytes]
[1 byte: to length][to bytes]
[2 bytes: body length][body bytes]
[1 byte: error]
```

Comparison:
JSON encoded message (bytes):
```
json_msg = {"cmd": "login", "src": "alice", "to": "server", "body": "This is a test message", "error": False, "msg_ids": '8d4a8912-5776-4438-ac14-8b791cfc63f2', "limit": 10}
```
Size: 162 bytes

Custom encoded message (bytes):
```
custom_msg = b'\x05login\x05alice\x06server\x00\x16This is a test message\x00\x00&"8d4a8912-5776-4438-ac14-8b791cfc63f2"\x00\n'
```
Size: 86 bytes

Comparison:
- JSON protocol size:   162 bytes
- Custom protocol size: 86 bytes

## Persistence and Fault Tolerance Design

### Requirements
1. Make the system persistent (survive restarts without losing messages)
2. Make the system 2-fault tolerant (operate correctly with up to 2 server failures)
3. Work across multiple machines

### Design Decisions

#### 1. Server Replication Architecture
We implemented a primary-backup replication model with the following components:
- Multiple server instances (minimum 3 for 2-fault tolerance)
- One primary server that handles client requests
- Multiple backup servers that replicate the primary's state
- Automatic failover mechanism when the primary fails

#### 2. Persistence Strategy
To make the system persistent, we will:
- Store user accounts and messages in local files on each server
- Implement write-ahead logging for all state changes
- Use append-only logs for message transactions
- Persist after each state-changing operation

#### 3. Replication Protocol
For reliable replication between servers:
- Primary server replicates all state changes to backup servers
- Use a simple acknowledgment-based consensus protocol
- Primary waits for majority acknowledgment before responding to clients
- Implement a heartbeat mechanism for failure detection

#### 4. Server States
Each server can be in one of these states:
- PRIMARY: Handles client connections and replicates changes
- BACKUP: Receives updates from the primary and stays ready for promotion
- CANDIDATE: Attempting to become the new primary during an election

#### 5. Failover Process
When primary failure is detected:
1. Backup servers enter CANDIDATE state
2. Simple election process (first to detect gets to be primary)
3. New primary notifies other backups of its status
4. Client connections are rerouted to the new primary

#### 6. Data Storage Format
User data will be stored in simple text files:
- users.txt: Username and password hash pairs
- messages_{username}.txt: Pending messages for each user
- server_state.txt: Current server state (PRIMARY/BACKUP)
- log.txt: Write-ahead log of all operations

#### 7. Client Modifications
The client will be modified to:
- Accept a list of server addresses instead of just one
- Attempt reconnection to backup servers when primary fails
- Cache outgoing messages during reconnection attempts

## Data Persistence and Message History Improvements

### Problem
The original implementation had some shortcomings in how user data and chat history were preserved:

1. When a primary server failed, there was no guaranteed mechanism to ensure all message history was transferred to the new primary.
2. Message history was deleted after being delivered to the user, preventing persistent access to conversation history.
3. During server transitions, client reconnection didn't properly restore message history.

### Solution

We implemented several improvements:

#### Enhanced Data Synchronization
* Added explicit data synchronization when a backup server becomes the primary
* Created `_request_data_sync()` to request data from peers when becoming primary
* Implemented `_handle_sync_request()` and `_handle_sync_data()` to transfer and process user and message data
* Built more robust sync mechanisms to ensure data consistency across servers

#### Message History Preservation
* Modified the `handle_deliver()` function to keep messages in storage by default
* Only remove messages when explicitly requested with a positive limit
* Ensured chat history is preserved across server restarts and primary/backup transitions

#### Client Reconnection Logic
* Improved client reconnect behavior with automatic session restoration
* Added `refresh_history()` method to fetch message history after reconnection
* Modified client's read_messages() to preserve messages (using limit=0)
* Enhanced reconnection logic to automatically restore chat state

These changes ensure seamless user experience even during server failures, with complete preservation of user data and chat history across the distributed system.

