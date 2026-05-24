import socket
import time
import sys

def wait_for_port(host: str = '127.0.0.1', port: int = 8188, timeout: int = 60) -> int:
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            print('COMFY_UP')
            return 0
        except Exception:
            time.sleep(1)
    print('TIMEOUT')
    return 2


if __name__ == '__main__':
    sys.exit(wait_for_port())
