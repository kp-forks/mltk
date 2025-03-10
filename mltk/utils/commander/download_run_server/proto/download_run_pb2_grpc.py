# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import download_run_pb2 as download__run__pb2


class DownloadRunStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.DownloadAndRun = channel.unary_stream(
                '/DownloadRun/DownloadAndRun',
                request_serializer=download__run__pb2.Request.SerializeToString,
                response_deserializer=download__run__pb2.Response.FromString,
                )


class DownloadRunServicer(object):
    """Missing associated documentation comment in .proto file."""

    def DownloadAndRun(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_DownloadRunServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'DownloadAndRun': grpc.unary_stream_rpc_method_handler(
                    servicer.DownloadAndRun,
                    request_deserializer=download__run__pb2.Request.FromString,
                    response_serializer=download__run__pb2.Response.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'DownloadRun', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class DownloadRun(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def DownloadAndRun(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_stream(request, target, '/DownloadRun/DownloadAndRun',
            download__run__pb2.Request.SerializeToString,
            download__run__pb2.Response.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
