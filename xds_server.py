from concurrent import futures
import grpc
import time

# Core xDS service and discovery protos
from proto.gen.envoy.service.discovery.v3 import ads_pb2_grpc
from proto.gen.envoy.service.discovery.v3 import discovery_pb2

# Envoy configuration protos for Listener and Cluster
from proto.gen.envoy.config.listener.v3 import listener_pb2

# Import listener_components_pb2 for FilterChain and Filter
from proto.gen.envoy.config.listener.v3 import listener_components_pb2

from proto.gen.envoy.config.cluster.v3 import cluster_pb2

# Envoy configuration protos for HTTP Connection Manager
from proto.gen.envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2

# Envoy configuration protos for Route (already correctly imported for route_pb2)
from proto.gen.envoy.config.route.v3 import route_pb2
from proto.gen.envoy.config.route.v3 import route_components_pb2

# Google Protobuf Any and Duration types
from google.protobuf import any_pb2
from google.protobuf import duration_pb2

class XdsServer(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    def StreamAggregatedResources(self, request_iterator, context):
        version_info = "1"
        nonce_counter = 0

        for request in request_iterator:
            type_url = request.type_url
            nonce_counter += 1
            current_nonce = str(nonce_counter)

            if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
                print(f"Received LDS request (nonce: {request.response_nonce})")

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

                route_config_any = any_pb2.Any()
                route_config_any.Pack(route_config)

                http_connection_manager = http_connection_manager_pb2.HttpConnectionManager(
                    stat_prefix="httpbin_ingress",
                    route_config=route_config,
                    http_filters=[
                        http_connection_manager_pb2.HttpFilter(
                            name="envoy.filters.http.router"
                        )
                    ],
                    common_http_protocol_options={
                        "idle_timeout": duration_pb2.Duration(seconds=300)
                    },
                )
                http_connection_manager_any = any_pb2.Any()
                http_connection_manager_any.Pack(http_connection_manager)

                listener = listener_pb2.Listener(
                    name="httpbin-demo",
                    address={
                        "socket_address": {
                            "address": "0.0.0.0",
                            "port_value": 15001
                        }
                    },
                    filter_chains=[
                        # **Use listener_components_pb2.FilterChain and Filter here**
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
                response = discovery_pb2.DiscoveryResponse(
                    version_info=version_info,
                    resources=[resource],
                    type_url=type_url,
                    nonce=current_nonce
                )
                yield response

            elif type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster":
                print(f"Received CDS request (nonce: {request.response_nonce})")
                cluster = cluster_pb2.Cluster(
                    name="httpbin_service",
                    connect_timeout=duration_pb2.Duration(seconds=5),
                    type=cluster_pb2.Cluster.LOGICAL_DNS,
                    lb_policy=cluster_pb2.Cluster.ROUND_ROBIN,
                    load_assignment={
                        "cluster_name": "httpbin_service",
                        "endpoints": [
                            {
                                "lb_endpoints": [
                                    {
                                        "endpoint": {
                                            "address": {
                                                "socket_address": {
                                                    "address": "httpbin",
                                                    "port_value": 8000
                                                }
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                )
                resource = any_pb2.Any()
                resource.Pack(cluster)
                response = discovery_pb2.DiscoveryResponse(
                    version_info=version_info,
                    resources=[resource],
                    type_url=type_url,
                    nonce=current_nonce
                )
                yield response
            else:
                print(f"Received unsupported type_url: {type_url}")
                response = discovery_pb2.DiscoveryResponse(
                    version_info=version_info,
                    resources=[],
                    type_url=type_url,
                    nonce=current_nonce
                )
                yield response


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ads_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(XdsServer(), server)
    server.add_insecure_port("[::]:5678")
    server.start()
    print("xDS server started on port 5678")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("xDS server stopping...")
        server.stop(0)


if __name__ == "__main__":
    serve()
