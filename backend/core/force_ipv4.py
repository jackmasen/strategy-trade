"""强制所有 HTTP 请求走 IPv4，解决交易所 IP 白名单只配了 IPv4 的问题。"""
import socket
import urllib3.util.connection as _u3conn

def _force_ipv4():
    return socket.AF_INET

_u3conn.allowed_gai_family = _force_ipv4
