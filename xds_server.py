from concurrent import futures
import grpc
import time
import hashlib
from google.protobuf import any_pb2
from google.protobuf import duration_pb2

# Core xDS service and discovery protos
from proto.gen.envoy.service.discovery.v3 import ads_pb2_grpc
from proto.gen.envoy.service.discovery.v3 import discovery_pb2

# Envoy configuration protos for Listener and Cluster
from proto.gen.envoy.config.listener.v3 import listener_pb2
from proto.gen.envoy.config.listener.v3 import listener_components_pb2
from proto.gen.envoy.config.cluster.v3 import cluster_pb2

# Endpoint components
from proto.gen.envoy.config.endpoint.v3 import endpoint_pb2
from proto.gen.envoy.config.endpoint.v3 import endpoint_components_pb2

# HTTP Connection Manager
from proto.gen.envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2
# HTTP Router Filter
from proto.gen.envoy.extensions.filters.http.router.v3 import router_pb2

# Route
from proto.gen.envoy.config.route.v3 import route_pb2
from proto.gen.envoy.config.route.v3 import route_components_pb2

# Core protos
from proto.gen.envoy.config.core.v3 import protocol_pb2
from proto.gen.envoy.config.core.v3 import address_pb2

# Upstream HTTP protocol options
from proto.gen.envoy.extensions.upstreams.http.v3 import http_protocol_options_pb2

class ConfigSnapshot:
    """Manages the current state of xDS configuration for different resource types."""
    def __init__(self):
        self.versions = {
            "type.googleapis.com/envoy.config.listener.v3.Listener": "0",
            "type.googleapis.com/envoy.config.cluster.v3.Cluster": "0",
        }
        self.nonces = {
            "type.googleapis.com/envoy.config.listener.v3.Listener": "",
            "type.googleapis.com/envoy.config.cluster.v3.Cluster": "",
        }
        self.config_hashes = {
            "type.googleapis.com/envoy.config.listener.v3.Listener": "",
            "type.googleapis.com/envoy.config.cluster.v3.Cluster": "",
        }
        self.resources = {
            "type.googleapis.com/envoy.config.listener.v3.Listener": None,
            "type.googleapis.com/envoy.config.cluster.v3.Cluster": None,
        }

    def get_version_info(self, type_url):
        return self.versions.get(type_url, "0"), self.nonces.get(type_url, "")

    def update_snapshot(self, type_url, new_config):
        """Updates the version and nonce only if the configuration has changed."""
        serialized_config = new_config.SerializeToString()
        current_hash = hashlib.sha1(serialized_config).hexdigest()

        if self.config_hashes.get(type_url) != current_hash:
            current_version = int(self.versions.get(type_url, "0"))
            self.versions[type_url] = str(current_version + 1)
            self.nonces[type_url] = str(int(time.time() * 1000000))
            self.config_hashes[type_url] = current_hash
            self.resources[type_url] = new_config
            print(f"[{time.time():.3f}] Config for {type_url} changed. New version: '{self.versions[type_url]}'")

        return self.versions[type_url], self.nonces[type_url], self.resources[type_url]

def generate_listener_config():
    """Generates the Listener configuration.

    This function builds a Listener resource that tells the Envoy proxy
    which network port to listen on and how to handle incoming HTTP requests.
    """

    # `RouteConfiguration` defines the routing logic. It's the "rulebook" that tells
    # Envoy where to send incoming requests based on their Host and path.
    route_config = route_pb2.RouteConfiguration(
        name="local_route",
        # Virtual hosts are a list of rules that match on the request's `Host` header.
        # This allows a single listener to handle traffic for multiple domains.
        virtual_hosts=[
            route_components_pb2.VirtualHost(
                name="httpbin_virtual_host",
                domains=["*"],
                routes=[
                    route_components_pb2.Route(
                        # `RouteMatch` defines which requests this rule applies to.
                        # `prefix="/"` matches any path starting with `/`, effectively all requests.
                        match=route_components_pb2.RouteMatch(prefix="/"),
                        # `RouteAction` specifies what to do with the matched request.
                        # We're forwarding it to the `httpbin_service` cluster.
                        route=route_components_pb2.RouteAction(cluster="httpbin_service")
                    )
                ]
            )
        ]
    )

    # The `HttpConnectionManager` is a network filter that handles all L7 (HTTP) traffic.
    # As a network filter that understands HTTP, it's the bridge
    # between the raw TCP connection and the higher-level HTTP protocol.
    router_config = router_pb2.Router()
    router_any = any_pb2.Any()
    router_any.Pack(router_config)

    http_connection_manager = http_connection_manager_pb2.HttpConnectionManager(
        stat_prefix="httpbin_ingress",
        route_config=route_config,
        # A list of HTTP filters that process the HTTP request after it has been parsed.
        # The `router` filter is mandatory for routing to an upstream cluster.
        http_filters=[
            http_connection_manager_pb2.HttpFilter(
                name="envoy.filters.http.router", # The canonical name for the HTTP router filter.
                typed_config=router_any
            )
        ],
        common_http_protocol_options=protocol_pb2.HttpProtocolOptions(
            idle_timeout=duration_pb2.Duration(seconds=300)
        ),
        request_timeout=duration_pb2.Duration(seconds=15),
    )
    # `Any` is a generic Protobuf wrapper. It's required for xDS to send different types
    # of resources (like a Listener or a Cluster) over the same stream.
    http_connection_manager_any = any_pb2.Any()
    # `Pack` serializes the `HttpConnectionManager` object and puts it inside the `Any` wrapper.
    http_connection_manager_any.Pack(http_connection_manager, type_url_prefix="type.googleapis.com/")

    # Define a listener on 0.0.0.0:15001 using TCP.
    # `HttpConnectionManager` is attached as the first network filter, to parse incoming TCP streams into HTTP requests.
    listener_address = address_pb2.Address(
        socket_address=address_pb2.SocketAddress(
            address="0.0.0.0",
            port_value=15001,
            protocol=address_pb2.SocketAddress.Protocol.TCP
        )
    )
    # The `Listener` is the top-level object in LDS. It binds the listener address to a
    # `FilterChain` which contains the filters that will process incoming connections.
    listener = listener_pb2.Listener(
        name="httpbin-demo",
        address=listener_address,
        filter_chains=[
            listener_components_pb2.FilterChain(
                filters=[
                    # A `FilterChain` is a pipeline of L4 (network) filters. Envoy processes
                    # a connection by passing it through each filter in this list.
                    listener_components_pb2.Filter(
                        name="envoy.filters.network.http_connection_manager",
                        typed_config=http_connection_manager_any
                    )
                ]
            )
        ]
    )
    return listener

def generate_cluster_config():
    """Generates the Cluster configuration.

    This function builds a Cluster resource, which tells Envoy about a group of
    identical upstream services (endpoints) it can send traffic to.
    """

    # `HttpProtocolOptions` configures how Envoy will talk to the upstream service.
    # We're explicitly setting it to use HTTP/1.1 here to ensure compatibility
    # with the `httpbin` service, which is a standard HTTP/1.1 application.
    http_upstream_protocol_options = http_protocol_options_pb2.HttpProtocolOptions()
    http_upstream_protocol_options.explicit_http_config.http_protocol_options.CopyFrom(
        protocol_pb2.Http1ProtocolOptions()
    )

    packed_http_proto_options = any_pb2.Any()
    packed_http_proto_options.Pack(http_upstream_protocol_options, type_url_prefix="type.googleapis.com/")

    # The `Cluster` object defines a group of identical upstream services.
    # It tells Envoy how to discover, connect to, and load balance traffic for them.
    cluster = cluster_pb2.Cluster(
        name="httpbin_service",
        connect_timeout=duration_pb2.Duration(seconds=5),
        # `DiscoveryType.LOGICAL_DNS` tells Envoy to resolve the cluster's address using DNS.
        type=cluster_pb2.Cluster.DiscoveryType.LOGICAL_DNS,
        # `LbPolicy.ROUND_ROBIN` distributes incoming requests evenly among the healthy endpoints.
        lb_policy=cluster_pb2.Cluster.LbPolicy.ROUND_ROBIN,
        load_assignment=endpoint_pb2.ClusterLoadAssignment(
            cluster_name="httpbin_service",
            endpoints=[
                endpoint_components_pb2.LocalityLbEndpoints(
                    lb_endpoints=[
                        endpoint_components_pb2.LbEndpoint(
                            endpoint=endpoint_components_pb2.Endpoint(
                                address=address_pb2.Address(
                                    socket_address=address_pb2.SocketAddress(
                                        # The hostname of the upstream service, which Docker's DNS will resolve.
                                        address="httpbin",
                                        # The port of the upstream service.
                                        port_value=8000
                                    )
                                )
                            )
                        )
                    ]
                )
            ]
        ),
        typed_extension_protocol_options={
            "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": packed_http_proto_options
        }
    )
    return cluster

class XdsServer(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    def __init__(self):
        super().__init__()
        self.config_snapshot = ConfigSnapshot()
        self.config_snapshot.update_snapshot(
            "type.googleapis.com/envoy.config.listener.v3.Listener",
            generate_listener_config()
        )
        self.config_snapshot.update_snapshot(
            "type.googleapis.com/envoy.config.cluster.v3.Cluster",
            generate_cluster_config()
        )

    def StreamAggregatedResources(self, request_iterator, context):
        for request in request_iterator:
            type_url = request.type_url
            envoy_known_version = request.version_info
            node_id = request.node.id

            is_nack = request.HasField('error_detail')

            # Initialize variables to avoid errors.
            version_info, nonce = self.config_snapshot.get_version_info(type_url)
            resource_obj = self.config_snapshot.resources.get(type_url)

            # Log initial requests and NACKs for visibility.
            if is_nack or envoy_known_version == "":
                print(f"[{time.time():.3f}] Received {type_url} request from node '{node_id}'")
                print(f"  Envoy's known version: '{envoy_known_version}'")
                if is_nack:
                    error_detail_message = request.error_detail.message
                    print(f"  *** Envoy NACKed previous config: '{error_detail_message}' ***")

            # On an initial request or ACK, regenerate the config and update the snapshot.
            if not is_nack:
                if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
                    listener = generate_listener_config()
                    version_info, nonce, resource_obj = self.config_snapshot.update_snapshot(type_url, listener)

                elif type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster":
                    cluster = generate_cluster_config()
                    version_info, nonce, resource_obj = self.config_snapshot.update_snapshot(type_url, cluster)

                else:
                    print(f"[{time.time():.3f}] Received unsupported type_url: {type_url}. Sending empty response.")

            # Build the response resources list based on the latest state.
            resources_to_send = []
            if resource_obj:
                resource = any_pb2.Any()
                resource.Pack(resource_obj)
                resources_to_send.append(resource)

            # Log the response details if a change was made or a NACK occurred.
            if is_nack or (version_info != envoy_known_version):
                print(f"  Serving config with server version: '{version_info}', response nonce: '{nonce}'")

            # Always yield a response to keep the gRPC stream open.
            response = discovery_pb2.DiscoveryResponse(
                version_info=version_info,
                resources=resources_to_send,
                type_url=type_url,
                nonce=nonce
            )
            yield response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ads_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(XdsServer(), server)
    server.add_insecure_port("[::]:5678")
    server.start()
    print(f"[{time.time():.3f}] xDS server started on port 5678")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print(f"[{time.time():.3f}] xDS server stopping...")
        server.stop(0)


if __name__ == "__main__":
    serve()