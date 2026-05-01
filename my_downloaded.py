"""
server.py - Network File System Server
CSC474/574 Computer Networks - Spring 2026

This server listens for TCP connections from clients and handles
file system operations: read, write, list, mkdir, rmdir, delete, copy, move.
Each client is handled in its own thread (multi-user support).
A reader-writer lock (RWLock) prevents simultaneous read/write on the same file (BONUS).
"""

import socket
import threading
import os
import shutil
import json

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
HOST = '0.0.0.0'       # Listen on all interfaces
PORT = 9000            # Port to listen on
BUFFER_SIZE = 4096     # Bytes per recv() call
ROOT_DIR = os.path.abspath('server_files')  # Root of the virtual file system

# ──────────────────────────────────────────────
# Reader-Writer Lock  (BONUS: Synchronization)
# ──────────────────────────────────────────────
class RWLock:
    """
    A simple Reader-Writer lock.
    - Multiple readers can hold the lock simultaneously.
    - A writer gets exclusive access; no readers allowed while writing.
    This prevents a user from reading a file while another is writing it.
    """
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0  # Count of active readers

    def acquire_read(self):
        """Acquire lock for reading (shared)."""
        with self._read_ready:
            self._readers += 1

    def release_read(self):
        """Release read lock."""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()  # Wake up any waiting writer

    def acquire_write(self):
        """Acquire lock for writing (exclusive). Blocks until all readers done."""
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()  # Wait until no readers

    def release_write(self):
        """Release write lock."""
        self._read_ready.release()


# Global dictionary: maps absolute file path -> RWLock
# This ensures one RWLock per file across all threads.
file_locks = {}
file_locks_mutex = threading.Lock()  # Protect the dictionary itself

def get_lock(filepath):
    """Get or create the RWLock for a given file path."""
    with file_locks_mutex:
        if filepath not in file_locks:
            file_locks[filepath] = RWLock()
        return file_locks[filepath]


# ──────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────
def safe_path(relative_path):
    """
    Resolve a client-provided path to an absolute server path.
    Prevents directory traversal attacks (e.g. '../../etc/passwd').
    Returns None if the path escapes ROOT_DIR.
    """
    abs_path = os.path.normpath(os.path.join(ROOT_DIR, relative_path.lstrip('/')))
    if not abs_path.startswith(ROOT_DIR):
        return None
    return abs_path


# ──────────────────────────────────────────────
# Command Handlers
# ──────────────────────────────────────────────

def cmd_list(args):
    """LIST <directory> — list files and subdirectories."""
    dir_rel = args[0] if args else ''
    dir_path = safe_path(dir_rel)
    if dir_path is None:
        return 'ERROR: Invalid path'
    if not os.path.isdir(dir_path):
        return f'ERROR: Directory not found: {dir_rel}'

    entries = []
    for entry in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, entry)
        tag = '[DIR] ' if os.path.isdir(full) else '[FILE]'
        entries.append(f'{tag} {entry}')
    return '\n'.join(entries) if entries else '(empty directory)'


def cmd_mkdir(args):
    """MKDIR <directory> — create a new directory."""
    if not args:
        return 'ERROR: Usage: MKDIR <directory>'
    dir_path = safe_path(args[0])
    if dir_path is None:
        return 'ERROR: Invalid path'
    if os.path.exists(dir_path):
        return f'ERROR: Already exists: {args[0]}'
    os.makedirs(dir_path)
    return f'OK: Directory created: {args[0]}'


def cmd_rmdir(args):
    """RMDIR <directory> — remove a directory (must be empty)."""
    if not args:
        return 'ERROR: Usage: RMDIR <directory>'
    dir_path = safe_path(args[0])
    if dir_path is None:
        return 'ERROR: Invalid path'
    if not os.path.isdir(dir_path):
        return f'ERROR: Not a directory: {args[0]}'
    try:
        shutil.rmtree(dir_path)
        return f'OK: Directory deleted: {args[0]}'
    except Exception as e:
        return f'ERROR: {e}'


def cmd_write(args, conn):
    """
    WRITE <filepath> <filesize>
    Receive file data from the client and save it to the server.
    Uses a write lock so no reader can access the file during the upload.
    """
    if len(args) < 2:
        return 'ERROR: Usage: WRITE <filepath> <filesize>'
    rel_path = args[0]
    try:
        filesize = int(args[1])
    except ValueError:
        return 'ERROR: Invalid filesize'

    abs_path = safe_path(rel_path)
    if abs_path is None:
        return 'ERROR: Invalid path'

    # Make sure the parent directory exists
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    lock = get_lock(abs_path)
    lock.acquire_write()
    try:
        # Tell the client we're ready
        conn.sendall(b'READY\n')

        # Receive exactly filesize bytes
        received = 0
        with open(abs_path, 'wb') as f:
            while received < filesize:
                chunk = conn.recv(min(BUFFER_SIZE, filesize - received))
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
        return f'OK: File written: {rel_path} ({received} bytes)'
    finally:
        lock.release_write()


def cmd_read(args, conn):
    """
    READ <filepath>
    Send the file contents to the client.
    Uses a read lock so multiple readers are fine, but blocks writers.
    """
    if not args:
        return 'ERROR: Usage: READ <filepath>'
    rel_path = args[0]
    abs_path = safe_path(rel_path)
    if abs_path is None:
        return 'ERROR: Invalid path'
    if not os.path.isfile(abs_path):
        return f'ERROR: File not found: {rel_path}'

    lock = get_lock(abs_path)
    lock.acquire_read()
    try:
        filesize = os.path.getsize(abs_path)
        # Send size so client knows how many bytes to read
        conn.sendall(f'SIZE {filesize}\n'.encode())

        with open(abs_path, 'rb') as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)
        return None  # Response already sent inline
    finally:
        lock.release_read()


def cmd_delete(args):
    """DELETE <filepath> — delete a file."""
    if not args:
        return 'ERROR: Usage: DELETE <filepath>'
    abs_path = safe_path(args[0])
    if abs_path is None:
        return 'ERROR: Invalid path'
    if not os.path.isfile(abs_path):
        return f'ERROR: File not found: {args[0]}'
    os.remove(abs_path)
    return f'OK: Deleted: {args[0]}'


def cmd_copy(args):
    """COPY <src> <dst> — copy a file on the server."""
    if len(args) < 2:
        return 'ERROR: Usage: COPY <src> <dst>'
    src = safe_path(args[0])
    dst = safe_path(args[1])
    if src is None or dst is None:
        return 'ERROR: Invalid path'
    if not os.path.isfile(src):
        return f'ERROR: Source not found: {args[0]}'
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return f'OK: Copied {args[0]} -> {args[1]}'


def cmd_move(args):
    """MOVE <src> <dst> — move/rename a file on the server."""
    if len(args) < 2:
        return 'ERROR: Usage: MOVE <src> <dst>'
    src = safe_path(args[0])
    dst = safe_path(args[1])
    if src is None or dst is None:
        return 'ERROR: Invalid path'
    if not os.path.exists(src):
        return f'ERROR: Source not found: {args[0]}'
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return f'OK: Moved {args[0]} -> {args[1]}'


# ──────────────────────────────────────────────
# Client Handler (runs in its own thread)
# ──────────────────────────────────────────────

def recv_line(conn):
    """Read bytes from socket until newline. Returns the line as a string."""
    data = b''
    while not data.endswith(b'\n'):
        chunk = conn.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode().strip()


def handle_client(conn, addr):
    """
    Main loop for one connected client.
    Parses commands and dispatches to handler functions.
    """
    print(f'[+] Client connected: {addr}')
    try:
        conn.sendall(b'Welcome to NFS Server. Type HELP for commands.\n')

        while True:
            line = recv_line(conn)
            if not line:
                break  # Client disconnected

            print(f'[{addr}] Command: {line}')
            parts = line.split()
            if not parts:
                continue

            cmd = parts[0].upper()
            args = parts[1:]
            response = None

            if cmd == 'HELP':
                response = (
                    'Commands:\n'
                    '  LIST [dir]          - List files in directory\n'
                    '  MKDIR <dir>         - Create directory\n'
                    '  RMDIR <dir>         - Remove directory\n'
                    '  WRITE <path> <size> - Upload file to server\n'
                    '  READ  <path>        - Download file from server\n'
                    '  DELETE <path>       - Delete a file\n'
                    '  COPY <src> <dst>    - Copy file on server\n'
                    '  MOVE <src> <dst>    - Move/rename file on server\n'
                    '  QUIT                - Disconnect'
                )
            elif cmd == 'LIST':
                response = cmd_list(args)
            elif cmd == 'MKDIR':
                response = cmd_mkdir(args)
            elif cmd == 'RMDIR':
                response = cmd_rmdir(args)
            elif cmd == 'WRITE':
                response = cmd_write(args, conn)
            elif cmd == 'READ':
                response = cmd_read(args, conn)
            elif cmd == 'DELETE':
                response = cmd_delete(args)
            elif cmd == 'COPY':
                response = cmd_copy(args)
            elif cmd == 'MOVE':
                response = cmd_move(args)
            elif cmd == 'QUIT':
                conn.sendall(b'Goodbye!\n')
                break
            else:
                response = f'ERROR: Unknown command: {cmd}'

            if response is not None:
                conn.sendall((response + '\n').encode())

    except Exception as e:
        print(f'[!] Error with client {addr}: {e}')
    finally:
        conn.close()
        print(f'[-] Client disconnected: {addr}')


# ──────────────────────────────────────────────
# Main — Start the server
# ──────────────────────────────────────────────

def main():
    # Create the root storage directory if it doesn't exist
    os.makedirs(ROOT_DIR, exist_ok=True)
    print(f'Server file root: {ROOT_DIR}')

    # Create a TCP socket
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(5)
    print(f'NFS Server listening on {HOST}:{PORT} ...')

    try:
        while True:
            conn, addr = server_sock.accept()
            # Each client gets its own thread (multi-user support)
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print('\nServer shutting down.')
    finally:
        server_sock.close()


if __name__ == '__main__':
    main()
