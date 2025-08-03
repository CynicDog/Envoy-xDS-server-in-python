PYTHONPATH=proto/gen uv run xds_server.py


docker run --rm --network xds-server-in-python_xds-net curlimages/curl curl -v http://xds-server-in-python-proxy-1:15001/headers
