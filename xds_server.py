from concurrent import futures
import grpc
import time

# Core xDS service and discovery protos
from proto.gen.envoy.service.discovery.v3 import ads_pb2_grpc
from proto.gen.envoy.service.discovery.v3 import discovery_pb2

# Envoy configuration protos for Listener and Cluster
from proto.gen.envoy.config.listener.v3 import listener_pb2
from proto.gen.envoy.config.listener.v3 import listener_components_pb2

from proto.gen.envoy.config.cluster.v3 import cluster_pb2

# Corrected Imports for Endpoint components
from proto.gen.envoy.config.endpoint.v3 import endpoint_pb2
from proto.gen.envoy.config.endpoint.v3 import endpoint_components_pb2

# Envoy configuration protos for HTTP Connection Manager
from proto.gen.envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2

# Envoy configuration protos for Route
from proto.gen.envoy.config.route.v3 import route_pb2
from proto.gen.envoy.config.route.v3 import route_components_pb2

# Google Protobuf Any and Duration types
from google.protobuf import any_pb2
from google.protobuf import duration_pb2

# Import protocol_pb2 for HttpProtocolOptions (common core options)
from proto.gen.envoy.config.core.v3 import protocol_pb2

# Import address_pb2 for Address and SocketAddress
from proto.gen.envoy.config.core.v3 import address_pb2

# NEW: Import the specific HttpProtocolOptions for UPSTREAM from extensions
from proto.gen.envoy.extensions.upstreams.http.v3 import http_protocol_options_pb2

# Global counters for versioning and nonce.
global_version_counter = 0

class XdsServer(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    def StreamAggregatedResources(self, request_iterator, context):
        global global_version_counter

        for request in request_iterator:
            type_url = request.type_url
            envoy_known_version = request.version_info
            envoy_response_nonce = request.response_nonce
            error_detail_message = request.error_detail.message if request.error_detail else "N/A"

            global_version_counter += 1
            current_server_version = str(global_version_counter)

            current_response_nonce = str(int(time.time() * 1000000))

            print(f"[{time.time():.3f}] Received {type_url} request from node '{request.node.id}'")
            print(f"  Envoy's known version: '{envoy_known_version}', Envoy's last acknowledged nonce: '{envoy_response_nonce}'")
            if error_detail_message != "N/A":
                print(f"  *** Envoy NACKed previous config: '{error_detail_message}' ***")
            print(f"  Serving config with server version: '{current_server_version}', response nonce: '{current_response_nonce}'")

            resources_to_send = []

            if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
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
                        idle_timeout=duration_pb2.Duration(seconds=300)
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
                resource = any_pb2.Any()
                resource.Pack(listener)
                resources_to_send.append(resource)

            elif type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster":
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
                resource = any_pb2.Any()
                resource.Pack(cluster)
                resources_to_send.append(resource)

            else:
                print(f"[{time.time():.3f}] Received unsupported type_url: {type_url}. Sending empty response.")
                pass

            response = discovery_pb2.DiscoveryResponse(
                version_info=current_server_version,
                resources=resources_to_send,
                type_url=type_url,
                nonce=current_response_nonce
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