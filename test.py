"""
test_nfs.py - Automated test for the Network File System
CSC474/574 Computer Networks - Spring 2026

Starts the server in a background thread, then runs client operations
against it to verify all commands work correctly.
Run with:  python test_nfs.py
"""

import socket
import threading
import time
import os
import sys
import shutil

# ── Import server and client logic ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
import server   # our server module
import client   # our client module

TEST_PORT = 9001
TEST_HOST = '127.0.0.1'
PASS = '\033[92mPASS\033[0m'
FAIL = '\033[91mFAIL\033[0m'

results = []

def check(description, condition):
    status = PASS if condition else FAIL
    print(f'  [{status}] {description}')
    results.append(condition)


def run_server():
    """Start the NFS server on TEST_PORT (runs in background thread)."""
    server.ROOT_DIR = os.path.abspath('test_server_files')
    os.makedirs(server.ROOT_DIR, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((TEST_HOST, TEST_PORT))
    srv.listen(5)
    srv.settimeout(5)
    while True:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(target=server.handle_client, args=(conn, addr), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except OSError:
            break


def connect():
    """Helper: return a connected socket to the test server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((TEST_HOST, TEST_PORT))
    client.recv_line(sock)  # consume greeting
    return sock


def test_all():
    print('\n=== Network File System Test Suite ===\n')

    # ── MKDIR ────────────────────────────────────────────────────────────────
    print('Testing MKDIR ...')
    sock = connect()
    client.send_cmd(sock, 'MKDIR testdir')
    r = client.recv_line(sock)
    check('mkdir testdir', r.startswith('OK'))
    sock.close()

    # ── LIST ─────────────────────────────────────────────────────────────────
    print('Testing LIST ...')
    sock = connect()
    client.send_cmd(sock, 'LIST')
    r = client.recv_line(sock)
    check('list root contains testdir', 'testdir' in r)
    sock.close()

    # ── WRITE (upload) ───────────────────────────────────────────────────────
    print('Testing WRITE (upload) ...')
    test_content = b'Hello from NFS client! This is test content.\n'
    with open('test_upload.txt', 'wb') as f:
        f.write(test_content)
    sock = connect()
    client.do_upload(sock, 'test_upload.txt', 'testdir/hello.txt')
    check('file exists on server',
          os.path.isfile(os.path.join(server.ROOT_DIR, 'testdir', 'hello.txt')))
    sock.close()

    # ── READ (download) ──────────────────────────────────────────────────────
    print('Testing READ (download) ...')
    sock = connect()
    client.do_download(sock, 'testdir/hello.txt', 'test_download.txt')
    with open('test_download.txt', 'rb') as f:
        downloaded = f.read()
    check('downloaded content matches uploaded', downloaded == test_content)
    sock.close()

    # ── COPY ─────────────────────────────────────────────────────────────────
    print('Testing COPY ...')
    sock = connect()
    client.send_cmd(sock, 'COPY testdir/hello.txt testdir/hello_copy.txt')
    r = client.recv_line(sock)
    check('copy returns OK', r.startswith('OK'))
    check('copy file exists',
          os.path.isfile(os.path.join(server.ROOT_DIR, 'testdir', 'hello_copy.txt')))
    sock.close()

    # ── MOVE ─────────────────────────────────────────────────────────────────
    print('Testing MOVE ...')
    sock = connect()
    client.send_cmd(sock, 'MOVE testdir/hello_copy.txt testdir/hello_moved.txt')
    r = client.recv_line(sock)
    check('move returns OK', r.startswith('OK'))
    check('moved file exists',
          os.path.isfile(os.path.join(server.ROOT_DIR, 'testdir', 'hello_moved.txt')))
    check('original removed',
          not os.path.isfile(os.path.join(server.ROOT_DIR, 'testdir', 'hello_copy.txt')))
    sock.close()

    # ── DELETE ───────────────────────────────────────────────────────────────
    print('Testing DELETE ...')
    sock = connect()
    client.send_cmd(sock, 'DELETE testdir/hello_moved.txt')
    r = client.recv_line(sock)
    check('delete returns OK', r.startswith('OK'))
    check('file removed',
          not os.path.isfile(os.path.join(server.ROOT_DIR, 'testdir', 'hello_moved.txt')))
    sock.close()

    # ── RMDIR ────────────────────────────────────────────────────────────────
    print('Testing RMDIR ...')
    sock = connect()
    client.send_cmd(sock, 'RMDIR testdir')
    r = client.recv_line(sock)
    check('rmdir returns OK', r.startswith('OK'))
    check('dir removed',
          not os.path.isdir(os.path.join(server.ROOT_DIR, 'testdir')))
    sock.close()

    # ── SYNCHRONIZATION (concurrent read & write) ─────────────────────────
    print('Testing Synchronization (concurrent read & write) ...')
    # Prepare a test file
    test_file_rel = 'sync_test.txt'
    test_file_abs = os.path.join(server.ROOT_DIR, test_file_rel)
    with open(test_file_abs, 'wb') as f:
        f.write(b'A' * 10000)

    lock = server.get_lock(test_file_abs)
    write_started = threading.Event()
    write_done = threading.Event()
    read_blocked_while_writing = []

    def writer():
        lock.acquire_write()
        write_started.set()
        time.sleep(0.3)  # Hold write lock for 300ms
        lock.release_write()
        write_done.set()

    def reader():
        write_started.wait()  # Wait until writer has the lock
        t0 = time.time()
        lock.acquire_read()
        elapsed = time.time() - t0
        read_blocked_while_writing.append(elapsed)
        lock.release_read()

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()
    wt.join(); rt.join()

    # Reader should have been blocked for ~0.3s while writer held the lock
    check('reader was blocked while writer held lock',
          read_blocked_while_writing and read_blocked_while_writing[0] > 0.1)

    # ── Summary ──────────────────────────────────────────────────────────────
    passed = sum(results)
    total = len(results)
    print(f'\n=== Results: {passed}/{total} tests passed ===\n')

    # Cleanup
    for f in ['test_upload.txt', 'test_download.txt']:
        if os.path.exists(f): os.remove(f)


if __name__ == '__main__':
    # Start server in background
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.5)  # Let server start up

    try:
        test_all()
    finally:
        # Clean up test server files
        if os.path.exists('test_server_files'):
            shutil.rmtree('test_server_files')
