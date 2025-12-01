import httpx


def make_http_client(
    *,
    max_connections: int = 20,
    max_keepalive_connections: int = 10,
    keepalive_expiry: float = 5.0,
    connect_timeout: None | float = 60.0,
    read_timeout: None | float = 60.0,
    pool_timeout: None | float = None,
) -> httpx.AsyncClient:
    """
    Instantiate an asynchronous http client.

    A common client should be used for multiple requests that can run asynchronously. The client
    will control the number of concurrent connections, etc.

    Args:
        max_connections: The maximum number of concurrent connections that may be established.
        max_keepalive_connections: Allow the connection pool to maintain keep-alive connections
            below this point. Should be less than or equal to max_connections.
        keepalive_expiry: Time limit on idle keep-alive connections in seconds.
        connect_timeout: Maximum amount of time to wait until a socket connection.
        read_timeout: Maximum duration to wait for a chunk of data to be received.
        pool_timeout: Maximum duration to wait for acquiring a connection from the connection
            pool.

    Returns:
        An httpx.AsyncClient instance configured with the specified limits and timeouts.
    """
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        keepalive_expiry=keepalive_expiry,
    )
    timeouts = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=None,  # Doesn't matter, we don't do writes.
        pool=pool_timeout,
    )
    return httpx.AsyncClient(limits=limits, timeout=timeouts)
