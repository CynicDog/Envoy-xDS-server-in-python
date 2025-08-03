# xDS-server-in-python

This project demonstrates a simple xDS server written in Python. It's designed to configure an Envoy proxy dynamically, directing incoming requests to an `httpbin` service. The setup includes three containers: an **xDS server**, an **Envoy proxy**, and a backend **httpbin** service.

## What it Does

The Python xDS server acts as the control plane, providing dynamic configuration to the Envoy proxy (the data plane). When a user sends a request to the proxy, it uses the configuration received from the xDS server to route the request to the correct upstream service, in this case, `httpbin`.

The core logic of the project is to serve three key configuration types:

* **LDS (Listener Discovery Service)**: Configures the port (`15001`) and the HTTP connection manager on the Envoy proxy, telling it to listen for incoming traffic.
* **CDS (Cluster Discovery Service)**: Defines the backend cluster, named `httpbin_service`, which points to the `httpbin` container.
* **RDS (Route Discovery Service)**: Defines the routing rules, specifying that all incoming requests (`/`) should be forwarded to the `httpbin_service` cluster.

The xDS protocol aggregates these services into a single stream, allowing the Envoy proxy to receive all necessary configurations through one continuous gRPC connection.

## Test Yourself\!

To see the project in action, follow these simple steps.

1.  Start the containers:

    ```bash
    docker compose up -d
    ```

2.  Run a `curl` command to send a request to the Envoy proxy on port `15001`. The proxy will then use its dynamically configured rules to forward the request to the `httpbin` service.

    ```bash
    docker run --rm --network xds-server-in-python_xds-net curlimages/curl curl -v http://my-envoy-proxy:15001/headers
    ```

### Expected Result

You'll see a response from the `httpbin` service, but the request will have passed through the Envoy proxy. The response headers will confirm this, showing `server: envoy` and `x-envoy-upstream-service-time`.

```
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0* Host my-envoy-proxy:15001 was resolved.
* IPv6: (none)
* IPv4: 172.19.0.4
* Trying 172.19.0.4:15001...
* Connected to my-envoy-proxy (172.19.0.4) port 15001
> GET /headers HTTP/1.1
> Host: my-envoy-proxy:15001
> User-Agent: curl/8.15.0
> Accept: */*
>
* Request completely sent off
< HTTP/1.1 200 OK
< server: envoy
< date: Sun, 03 Aug 2025 09:16:58 GMT
< content-type: application/json
< access-control-allow-origin: *
< access-control-allow-credentials: true
< content-length: 237
< x-envoy-upstream-service-time: 29
{
  "headers": {
    "Accept": "*/*",
    "Host": "xds-server-in-python-proxy-1:15001",
    "User-Agent": "curl/8.15.0",
    "X-Envoy-Expected-Rq-Timeout-Ms": "15000",
    "X-Request-Id": "ee63eca7-a284-475d-9d62-91bf12060cc4"
  }
}
```

## Unsung Heroes: `uv` and `buf`

This project leverages some powerful tools to streamline development and dependency management:

* **`uv`**: A modern, high-performance Python package manager and installer written in Rust. It's an incredibly fast drop-in replacement for traditional tools like `pip` and `virtualenv`, helping to create a lean and efficient development environment.
* **`buf`**: A state-of-the-art build tool for Protocol Buffers. It ensures consistency and best practices for `.proto` files by providing linting, breaking change detection, and a faster compiler than the standard `protoc`. This project uses `buf` to manage the Protobuf schema and generate the Python code, ensuring the API definitions are always correct.
