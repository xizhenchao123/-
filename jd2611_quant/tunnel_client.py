#!/usr/bin/env python3
"""
Connect to localhost.run via SSH and print the tunnel URL.
"""
import subprocess, re, sys, time

cmd = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=15",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ProxyCommand=socat - PROXY:127.0.0.1:%h:%p,proxyport=18080",
    "-R", "80:localhost:8501",
    "-N", "nokey@localhost.run",
]

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    universal_newlines=True,
)

url_pattern = re.compile(r"https://([a-zA-Z0-9-]+\.lhr\.life)")
start = time.time()
found_url = None

while time.time() - start < 30:
    line = proc.stdout.readline()
    if not line:
        break
    sys.stdout.write(line)
    sys.stdout.flush()
    m = url_pattern.search(line)
    if m:
        found_url = m.group(0)
        print(f"\n=== TUNNEL_URL={found_url} ===", flush=True)

if not found_url:
    print("TUNNEL_URL_NOT_FOUND", flush=True)
    proc.terminate()
else:
    # Keep running
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()