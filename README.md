# Network File System (NFS)
## CSC474/574 Computer Networks — Spring 2026
**Student:** Wilson Jr Hiyas  
**Language:** Python 3  
**Project Management:** Git / GitHub  
**GitHub Repo:** https://github.com/WilsonXAdonai/Wilsoncscomputernetworks.git

---

## 1. Project Overview

This project implements a **client-server Network File System** using Python TCP sockets.
A client connects to the server over a TCP connection and can create directories, upload
files, download files, list directory contents, copy, move, and delete files.

The server runs locally on one machine. The client can connect from any machine on the
same network, or from anywhere on the Internet if port forwarding is configured.

---

## 2. Files Included

| File | Description |
|------|-------------|
| `server.py` | NFS server — listens for TCP connections, handles all file operations |
| `client.py` | Interactive NFS client — connects to server and sends commands |
| `test_nfs.py` | Automated test suite — runs all 14 tests automatically |
| `README.md` | This report |
| `.gitignore` | Git ignore rules |

---

## 3. How to Run the Program

### Requirements
- Python 3.x (no external libraries needed — uses only Python standard library)
- Two terminal windows open at the same time

---

### Step 1 — Start the Server

Open a terminal and run:

```bash
python server.py
```

Expected output:
```
Server file root: C:\Users\...\nfs_project\server_files
NFS Server listening on 0.0.0.0:9000 ...
```

The server is now running and waiting for clients to connect.
It automatically creates a `server_files/` folder to store all uploaded files.

---

### Step 2 — Start the Client

Open a **second terminal** and run:

```bash
python client.py
```

To connect to a different machine (remote server):
```bash
python client.py <server_ip_address> 9000
```

Expected output:
```
Connecting to NFS server at 127.0.0.1:9000 ...
Welcome to NFS Server. Type HELP for commands.
nfs>
```

---

### Step 3 — Use the File System

Once connected, type commands at the `nfs>` prompt:

| Command | What it does | Example |
|---------|-------------|---------|
| `mkdir <dir>` | Create a directory | `mkdir homework` |
| `rmdir <dir>` | Delete a directory | `rmdir homework` |
| `list [dir]` | List files in a directory | `list` or `list homework` |
| `upload <local> <remote>` | Upload a file to server | `upload report.txt homework/report.txt` |
| `download <remote> <local>` | Download file from server | `download homework/report.txt copy.txt` |
| `copy <src> <dst>` | Copy a file on server | `copy homework/a.txt homework/b.txt` |
| `move <src> <dst>` | Move or rename a file | `move homework/a.txt docs/a.txt` |
| `delete <path>` | Delete a file | `delete homework/report.txt` |
| `quit` | Disconnect | `quit` |

---

### Step 4 — Run the Automated Tests

Stop the server first (Ctrl+C), then run:

```bash
python test_nfs.py
```

Expected output:
```
=== Network File System Test Suite ===
  [PASS] mkdir testdir
  [PASS] list root contains testdir
  [PASS] file exists on server
  [PASS] downloaded content matches uploaded
  [PASS] copy returns OK
  [PASS] copy file exists
  [PASS] move returns OK
  [PASS] moved file exists
  [PASS] original removed
  [PASS] delete returns OK
  [PASS] file removed
  [PASS] rmdir returns OK
  [PASS] dir removed
  [PASS] reader was blocked while writer held lock

=== Results: 14/14 tests passed ===
```

---

## 4. How Program Requirements Are Addressed

### TCP & Socket Programming (Objective)
- `server.py` creates a `socket.AF_INET` + `socket.SOCK_STREAM` socket — this is a standard Internet TCP socket
- The server binds to `0.0.0.0:9000` which means it listens on all network interfaces
- `client.py` connects using `socket.connect((host, port))`
- All data transfer uses raw TCP byte streams — no HTTP, no external libraries

### Read Files
- `READ` command: server sends the file size first, then streams the raw bytes
- Client receives exactly that many bytes and saves to local disk

### Write Files
- `WRITE` command: client sends the file size first, then streams the raw bytes
- Server receives exactly that many bytes and saves to `server_files/`

### List Files in a Directory
- `LIST` command: server reads the directory using `os.listdir()` and returns each entry tagged as `[FILE]` or `[DIR]`

### Create Directories
- `MKDIR` command: server calls `os.makedirs()` to create the directory

### Delete Directories
- `RMDIR` command: server calls `shutil.rmtree()` to remove the directory and all contents

### Copy and Move Files
- `COPY` command: server uses `shutil.copy2()` to copy a file within the server
- `MOVE` command: server uses `shutil.move()` to move or rename a file

### Serve Multiple Users Simultaneously
- Every client that connects gets its own `threading.Thread`
- This means 2, 5, or 100 clients can all be connected and active at the same time
- Each thread runs `handle_client()` independently

### Remotely Accessible from the Internet
- The server binds to `HOST = '0.0.0.0'` which means it accepts connections from any IP address
- To access from the Internet: enable port forwarding on router for port 9000, then clients connect using the server's public IP:
  ```bash
  python client.py <public_ip> 9000
  ```
- For cloud deployment (AWS, GCP, etc.): launch a VM, open port 9000 in the security group, run `python server.py`

### Synchronization — BONUS ✅
- A custom `RWLock` (Reader-Writer Lock) class is implemented in `server.py`
- **Problem it solves:** Two users cannot read and write the same file at the same time
- **How it works:**
  - Multiple users CAN read the same file simultaneously (shared lock)
  - Only ONE user can write at a time — all readers are blocked until writing finishes (exclusive lock)
- Each file gets its own `RWLock` stored in a global dictionary
- The dictionary itself is protected by a `threading.Lock` to prevent race conditions

---

## 5. Architecture

```
  Client 1 (Terminal 2) ──┐
  Client 2 (Terminal 3) ──┤──► TCP Port 9000 ──► Server (main thread: accept loop)
  Client 3 (Terminal 4) ──┘                              │
                                                         ├─► Thread 1 → handles Client 1
                                                         ├─► Thread 2 → handles Client 2
                                                         └─► Thread 3 → handles Client 3
                                                                  │
                                                         RWLock per file (synchronization)
                                                                  │
                                                         server_files/        ← physical storage
                                                         ├── homework/
                                                         │   └── report.txt
                                                         └── docs/
                                                             └── notes.txt
```

---

## 6. Security

- `safe_path()` function prevents **directory traversal attacks**
  - Example attack: a malicious client sending `../../etc/passwd` as a file path
  - The function resolves all paths and verifies they stay inside `server_files/`
  - Any path that escapes the root directory returns an error

---

## 7. Git / Project Management

Git was used throughout development to track all changes.

```bash
# View commit history
git log --oneline
```

GitHub repository: https://github.com/arai8842/CSC474