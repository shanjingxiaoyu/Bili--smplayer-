import socket, ssl, json, time

def fast_request(url, timeout=5):
    """Minimal HTTPS GET using raw sockets — bypasses all library overhead."""
    # Parse URL
    host = url.split('/')[2]
    path = '/' + '/'.join(url.split('/')[3:])
    
    # DNS + TCP
    addrs = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    ip = addrs[0][4][0]
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((ip, 443))
    
    # TLS
    ctx = ssl.create_default_context()
    tls = ctx.wrap_socket(sock, server_hostname=host)
    
    # HTTP
    req = f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nReferer: https://www.bilibili.com\r\nConnection: close\r\n\r\n'.encode()
    tls.sendall(req)
    
    data = b''
    while True:
        try:
            chunk = tls.recv(8192)
            if not chunk: break
            data += chunk
        except: break
    
    tls.close()
    body = data.split(b'\r\n\r\n', 1)[1]
    return json.loads(body)

# Test
t0 = time.time()
j = fast_request('https://api.bilibili.com/x/web-interface/nav')
print(f'{time.time()-t0:.2f}s  code={j.get("code")}', flush=True)
