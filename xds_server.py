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
            # This is the only place we log a successful update
            print(f"[{time.time():.3f}] Config for {type_url} changed. New version: '{self.versions[type_url]}'")

        return self.versions[type_url], self.nonces[type_url], self.resources[type_url]

def generate_listener_config():
    """Generates the Listener configuration."""
    route_config = route_pb2.RouteConfiguration(
        name="local_route",
        virtual_hosts=[
            route_components_pb2.VirtualHost(
                name="httpbin_virtual_host",
                domains=["*"],
                routes=[
                    route_components_pb2.Route(
                        match=route_components_pb2.RouteMatch(prefix="/"),
                        route=route_components_pb2.RouteAction(cluster="httpbin_service")
                    )
                ]
            )
        ]
    )

    http_connection_manager = http_connection_manager_pb2.HttpConnectionManager(
        stat_prefix="httpbin_ingress",
        route_config=route_config,
        http_filters=[
            http_connection_manager_pb2.HttpFilter(
                name="envoy.filters.http.router"
            )
        ],
        common_http_protocol_options=protocol_pb2.HttpProtocolOptions(
            idle_timeout=duration_pb2.Duration(seconds=3000)
        ),
        request_timeout=duration_pb2.Duration(seconds=15),
    )

    http_connection_manager_any = any_pb2.Any()
    http_connection_manager_any.Pack(http_connection_manager, type_url_prefix="type.googleapis.com/")

    listener_address = address_pb2.Address(
        socket_address=address_pb2.SocketAddress(
            address="0.0.0.0",
            port_value=15001,
            protocol=address_pb2.SocketAddress.Protocol.TCP
        )
    )

    listener = listener_pb2.Listener(
        name="httpbin-demo",
        address=listener_address,
        filter_chains=[
            listener_components_pb2.FilterChain(
                filters=[
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
    """Generates the Cluster configuration."""
    http_upstream_protocol_options = http_protocol_options_pb2.HttpProtocolOptions()
    http_upstream_protocol_options.explicit_http_config.http_protocol_options.CopyFrom(
        protocol_pb2.Http1ProtocolOptions()
    )

    packed_http_proto_options = any_pb2.Any()
    packed_http_proto_options.Pack(http_upstream_protocol_options, type_url_prefix="type.googleapis.com/")

    cluster = cluster_pb2.Cluster(
        name="httpbin_service",
        connect_timeout=duration_pb2.Duration(seconds=5),
        type=cluster_pb2.Cluster.DiscoveryType.LOGICAL_DNS,
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
                                        address="httpbin",
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
        # Initialize snapshot with initial configuration.
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
            error_detail_message = request.error_detail.message if is_nack else "N/A"

            # Log only initial requests and NACKs
            if is_nack or envoy_known_version == "":
                print(f"[{time.time():.3f}] Received {type_url} request from node '{node_id}'")
                print(f"  Envoy's known version: '{envoy_known_version}'")

            if is_nack:
                print(f"  *** Envoy NACKed previous config: '{error_detail_message}' ***")
                # When NACKed, we simply resend the last known good configuration
                version_info, nonce = self.config_snapshot.get_version_info(type_url)
                resource_obj = self.config_snapshot.resources.get(type_url)

                resources_to_send = []
                if resource_obj:
                    resource = any_pb2.Any()
                    resource.Pack(resource_obj)
                    resources_to_send.append(resource)
            else:
                # This is an ACK or an initial request.
                resources_to_send = []
                if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
                    listener = generate_listener_config()
                    version_info, nonce, resource_obj = self.config_snapshot.update_snapshot(type_url, listener)
                    resource = any_pb2.Any()
                    resource.Pack(resource_obj)
                    resources_to_send.append(resource)

                elif type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster":
                    cluster = generate_cluster_config()
                    version_info, nonce, resource_obj = self.config_snapshot.update_snapshot(type_url, cluster)
                    resource = any_pb2.Any()
                    resource.Pack(resource_obj)
                    resources_to_send.append(resource)

                else:
                    version_info, nonce = self.config_snapshot.get_version_info(type_url)
                    print(f"[{time.time():.3f}] Received unsupported type_url: {type_url}. Sending empty response.")

            # Print server response details only when a change is made or a NACK occurs
            if is_nack or (version_info != envoy_known_version):
                print(f"  Serving config with server version: '{version_info}', response nonce: '{nonce}'")

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