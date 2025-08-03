from concurrent import futures
import grpc
import time

# Core xDS service and discovery protos
from proto.gen.envoy.service.discovery.v3 import ads_pb2_grpc
from proto.gen.envoy.service.discovery.v3 import discovery_pb2

# Envoy configuration protos for Listener and Cluster
from proto.gen.envoy.config.listener.v3 import listener_pb2
from proto.gen.envoy.config.cluster.v3 import cluster_pb2

# Envoy configuration protos for HTTP Connection Manager and Route
from proto.gen.envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2
from proto.gen.envoy.config.route.v3 import route_pb2

# Google Protobuf Any and Duration types
from google.protobuf import any_pb2
from google.protobuf import duration_pb2

class XdsServer(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    def StreamAggregatedResources(self, request_iterator, context):
        # Initial version and nonce (can be incremented for updates)
        version_info = "1"
        nonce_counter = 0

        # Loop indefinitely to serve discovery requests
        # In a real-world scenario, you might want to yield new configurations
        # based on external events or configuration changes.
        # For this example, we'll respond to each request with the same config.
        for request in request_iterator:
            type_url = request.type_url
            nonce_counter += 1
            current_nonce = str(nonce_counter)

            if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
                print(f"Received LDS request (nonce: {request.response_nonce})")

                # 1. Define the RouteConfiguration
                # This specifies how incoming requests are routed to clusters.
                route_config = route_pb2.RouteConfiguration(
                    name="local_route",
                    virtual_hosts=[
                        route_pb2.VirtualHost(
                            name="httpbin_virtual_host",
                            domains=["*"],  # Match all domains/hosts
                            routes=[
                                route_pb2.Route(
                                    match=route_pb2.RouteMatch(prefix="/"), # Match all incoming paths
                                    route=route_pb2.RouteAction(cluster="httpbin_service") # Route to the 'httpbin_service' cluster
                                )
                            ]
                        )
                    ]
                )

                # 2. Pack the RouteConfiguration into an Any message for the HttpConnectionManager
                route_config_any = any_pb2.Any()
                # The type_url for RouteConfiguration is important
                route_config_any.Pack(route_config)

                # 3. Define the HttpConnectionManager
                # This filter handles HTTP requests on the listener.
                http_connection_manager = http_connection_manager_pb2.HttpConnectionManager(
                    stat_prefix="httpbin_ingress",
                    # Specify the route configuration. Here we inline it directly.
                    # For RDS (Route Discovery Service), you would use `rds.route_config_name`.
                    route_config=route_config,
                    http_filters=[
                        http_connection_manager_pb2.HttpFilter(
                            name="envoy.filters.http.router" # The standard Envoy HTTP router filter
                        )
                    ]
                )

                # 4. Pack the HttpConnectionManager into an Any message for the Listener filter
                http_connection_manager_any = any_pb2.Any()
                # The type_url for HttpConnectionManager is important
                http_connection_manager_any.Pack(http_connection_manager)

                # 5. Define the Listener with the FilterChain
                listener = listener_pb2.Listener(
                    name="httpbin-demo",
                    address={
                        "socket_address": {
                            "address": "0.0.0.0",
                            "port_value": 15001
                        }
                    },
                    filter_chains=[
                        listener_pb2.FilterChain(
                            filters=[
                                listener_pb2.Filter(
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
                    name="httpbin_service", # This name must match the cluster name in the RouteAction
                    connect_timeout=duration_pb2.Duration(seconds=5),
                    type=cluster_pb2.Cluster.LOGICAL_DNS, # Use LOGICAL_DNS for Docker service names
                    lb_policy=cluster_pb2.Cluster.ROUND_ROBIN,
                    load_assignment={
                        "cluster_name": "httpbin_service", # This also matches the cluster name
                        "endpoints": [
                            {
                                "lb_endpoints": [
                                    {
                                        "endpoint": {
                                            "address": {
                                                "socket_address": {
                                                    "address": "httpbin", # Docker service name for httpbin
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
                # You might want to yield an empty DiscoveryResponse or an error
                # for unsupported types, depending on your desired behavior.
                response = discovery_pb2.DiscoveryResponse(
                    version_info=version_info,
                    resources=[],
                    type_url=type_url,
                    nonce=current_nonce
                )
                yield response


def serve():
    # Use a ThreadPoolExecutor for handling gRPC requests concurrently
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # Add the AggregatedDiscoveryService servicer to the gRPC server
    ads_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(XdsServer(), server)
    # Listen on all interfaces on port 5678 (for Docker Compose)
    server.add_insecure_port("[::]:5678")
    server.start()
    print("xDS server started on port 5678")
    try:
        # Keep the server running until terminated
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("xDS server stopping...")
        server.stop(0)


if __name__ == "__main__":
    serve()
