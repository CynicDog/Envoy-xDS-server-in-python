from concurrent import futures
import grpc
import time

from proto.gen.envoy.service.discovery.v3 import ads_pb2_grpc
from proto.gen.envoy.service.discovery.v3 import discovery_pb2
from proto.gen.envoy.config.listener.v3 import listener_pb2
from proto.gen.envoy.config.cluster.v3 import cluster_pb2
from google.protobuf import any_pb2
from google.protobuf import duration_pb2

class XdsServer(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    def StreamAggregatedResources(self, request_iterator, context):
        for request in request_iterator:
            type_url = request.type_url
            version_info = "1"

            if type_url == "type.googleapis.com/envoy.config.listener.v3.Listener":
                print("Received LDS request")
                listener = listener_pb2.Listener(
                    name="httpbin-demo",
                    address={
                        "socket_address": {
                            "address": "0.0.0.0",
                            "port_value": 15001
                        }
                    }
                )
                resource = any_pb2.Any()
                resource.Pack(listener)
                response = discovery_pb2.DiscoveryResponse(
                    version_info=version_info,
                    resources=[resource],
                    type_url=type_url,
                    nonce="1"
                )
                yield response

            elif type_url == "type.googleapis.com/envoy.config.cluster.v3.Cluster":
                print("Received CDS request")
                cluster = cluster_pb2.Cluster(
                    name="httpbin_service",
                    connect_timeout=duration_pb2.Duration(seconds=5),
                    type=cluster_pb2.Cluster.LOGICAL_DNS,
                    lb_policy=cluster_pb2.Cluster.ROUND_ROBIN,
                    load_assignment={
                        "cluster_name": "httpbin",
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
                    nonce="1"
                )
                yield response

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ads_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(XdsServer(), server)
    server.add_insecure_port("[::]:5678")
    server.start()
    print("xDS server started on port 5678")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
