"""
client.py - Network File System Client
CSC474/574 Computer Networks - Spring 2026

This client connects to the NFS server via TCP and provides an
interactive shell for file system operations.
"""

import socket
import os
import sys

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
DEFAULT_HOST = '127.0.0.1'  # Server IP (localhost for local testing)
DEFAULT_PORT = 9000          # Must match server PORT
BUFFER_SIZE = 4096


# ──────────────────────────────────────────────
# Low-level communication helpers
# ──────────────────────────────────────────────

def recv_line(sock):
    """Read one line (terminated by newline) from the socket."""
    data = b''
    while not data.endswith(b'\n'):
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode().strip()


def send_cmd(sock, command):
    """Send a command string to the server (adds newline)."""
    sock.sendall((command + '\n').encode())


def recv_response(sock):
    """Receive and print a single-line response from the server."""
    line = recv_line(sock)
    print(line)
    return line


def recv_multiline(sock):
    """
    Receive a multi-line response. The server sends the full text
    followed by a blank line. We stop after the first non-blank
    line that is followed by a blank.
    
    For simplicity, we read until a line starting with 'OK' or 'ERROR'
    or until we detect the end of a greeting/help block.
    """
    lines = []
    while True:
        line = recv_line(sock)
        lines.append(line)
        # Server ends multi-line with the final status line
        if line.startswith('OK') or line.startswith('ERROR') or line == '':
            break
    return '\n'.join(lines)


# ──────────────────────────────────────────────
# Client Commands
# ──────────────────────────────────────────────

def do_list(sock, remote_dir=''):
    """Send LIST command and print the directory listing."""
    cmd = f'LIST {remote_dir}'.strip()
    send_cmd(sock, cmd)
    # Read until we get a line that doesn't look like a file entry
    print('\n--- Directory Listing ---')
    while True:
        line = recv_line(sock)
        print(line)
        # The server sends all entries then stops; we detect the end
        # by checking if the next char is available — simplest approach:
        # read until we get an empty line (our protocol sends \n after each response)
        # Actually: server sends the full response + '\n'. For LIST it's one big string.
        break  # recv_line already reads one full response block
    print('-------------------------')


def do_mkdir(sock, remote_dir):
    """Send MKDIR command."""
    send_cmd(sock, f'MKDIR {remote_dir}')
    print(recv_line(sock))


def do_rmdir(sock, remote_dir):
    """Send RMDIR command."""
    send_cmd(sock, f'RMDIR {remote_dir}')
    print(recv_line(sock))


def do_upload(sock, local_path, remote_path):
    """
    Upload a local file to the server using the WRITE command.
    Protocol:
      Client -> WRITE <remote_path> <filesize>\n
      Server -> READY\n
      Client -> <raw file bytes>
      Server -> OK: ...\n
    """
    if not os.path.isfile(local_path):
        print(f'ERROR: Local file not found: {local_path}')
        return

    filesize = os.path.getsize(local_path)
    send_cmd(sock, f'WRITE {remote_path} {filesize}')

    # Wait for server to say it's ready
    ready = recv_line(sock)
    if ready != 'READY':
        print(f'ERROR: Server not ready: {ready}')
        return

    # Send the file bytes
    sent = 0
    with open(local_path, 'rb') as f:
        while True:
            chunk = f.read(BUFFER_SIZE)
            if not chunk:
                break
            sock.sendall(chunk)
            sent += len(chunk)

    # Read final response
    response = recv_line(sock)
    print(response)
    print(f'  Uploaded {sent} bytes.')


def do_download(sock, remote_path, local_path):
    """
    Download a file from the server using the READ command.
    Protocol:
      Client -> READ <remote_path>\n
      Server -> SIZE <filesize>\n   (or ERROR ...)
      Server -> <raw file bytes>
    """
    send_cmd(sock, f'READ {remote_path}')

    # First response: either SIZE or ERROR
    first = recv_line(sock)
    if first.startswith('ERROR'):
        print(first)
        return

    if not first.startswith('SIZE'):
        print(f'ERROR: Unexpected server response: {first}')
        return

    filesize = int(first.split()[1])
    print(f'Downloading {filesize} bytes ...')

    received = 0
    with open(local_path, 'wb') as f:
        while received < filesize:
            chunk = sock.recv(min(BUFFER_SIZE, filesize - received))
            if not chunk:
                break
            f.write(chunk)
            received += len(chunk)

    print(f'OK: Downloaded {remote_path} -> {local_path} ({received} bytes)')


def do_delete(sock, remote_path):
    """Send DELETE command."""
    send_cmd(sock, f'DELETE {remote_path}')
    print(recv_line(sock))


def do_copy(sock, src, dst):
    """Send COPY command (server-side copy)."""
    send_cmd(sock, f'COPY {src} {dst}')
    print(recv_line(sock))


def do_move(sock, src, dst):
    """Send MOVE command (server-side move/rename)."""
    send_cmd(sock, f'MOVE {src} {dst}')
    print(recv_line(sock))


def print_help():
    """Print local client help."""
    print("""
NFS Client Commands:
  list [remote_dir]          - List files in remote directory
  mkdir <remote_dir>         - Create remote directory
  rmdir <remote_dir>         - Remove remote directory
  upload <local> <remote>    - Upload local file to server
  download <remote> <local>  - Download file from server
  delete <remote_path>       - Delete file on server
  copy <src> <dst>           - Copy file on server
  move <src> <dst>           - Move/rename file on server
  help                       - Show this help
  quit                       - Disconnect and exit
""")


# ──────────────────────────────────────────────
# Main interactive shell
# ──────────────────────────────────────────────

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    print(f'Connecting to NFS server at {host}:{port} ...')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
    except ConnectionRefusedError:
        print('ERROR: Could not connect to server. Is it running?')
        sys.exit(1)

    # Print server greeting
    greeting = recv_line(sock)
    print(greeting)
    print_help()

    # Interactive command loop
    while True:
        try:
            line = input('nfs> ').strip()
        except (EOFError, KeyboardInterrupt):
            line = 'quit'

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ('quit', 'exit'):
            send_cmd(sock, 'QUIT')
            print(recv_line(sock))
            break
        elif cmd == 'help':
            print_help()
        elif cmd == 'list':
            do_list(sock, parts[1] if len(parts) > 1 else '')
        elif cmd == 'mkdir' and len(parts) >= 2:
            do_mkdir(sock, parts[1])
        elif cmd == 'rmdir' and len(parts) >= 2:
            do_rmdir(sock, parts[1])
        elif cmd == 'upload' and len(parts) >= 3:
            do_upload(sock, parts[1], parts[2])
        elif cmd == 'download' and len(parts) >= 3:
            do_download(sock, parts[1], parts[2])
        elif cmd == 'delete' and len(parts) >= 2:
            do_delete(sock, parts[1])
        elif cmd == 'copy' and len(parts) >= 3:
            do_copy(sock, parts[1], parts[2])
        elif cmd == 'move' and len(parts) >= 3:
            do_move(sock, parts[1], parts[2])
        else:
            print('Unknown command or missing arguments. Type "help" for usage.')

    sock.close()
    print('Disconnected.')


if __name__ == '__main__':
    main()
