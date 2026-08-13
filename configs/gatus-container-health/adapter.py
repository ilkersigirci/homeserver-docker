import http.client
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit

DOCKER_HOST = urlsplit(os.environ["DOCKER_HOST"])
COMPOSE_PROJECT_NAME = os.environ["COMPOSE_PROJECT_NAME"]
DOCKER_TIMEOUT = 5
API_VERSION_PATTERN = re.compile(r"\d+\.\d+")


def docker_json(connection, path):
    connection.request("GET", path)
    response = connection.getresponse()
    if response.status != 200:
        raise RuntimeError(f"Docker API returned {response.status} for {path}")
    return json.load(response)


def docker_api_version(connection):
    version = docker_json(connection, "/version")
    if not isinstance(version, dict):
        raise ValueError("Docker API version response was not an object")

    api_version = version.get("ApiVersion")
    if not isinstance(api_version, str) or not API_VERSION_PATTERN.fullmatch(
        api_version
    ):
        raise ValueError("Docker API returned an invalid ApiVersion")
    return api_version


def unhealthy_container_names():
    filters = json.dumps(
        {
            "health": ["unhealthy"],
            "label": [f"com.docker.compose.project={COMPOSE_PROJECT_NAME}"],
        },
        separators=(",", ":"),
    )
    connection = http.client.HTTPConnection(
        DOCKER_HOST.hostname,
        DOCKER_HOST.port,
        timeout=DOCKER_TIMEOUT,
    )
    try:
        api_version = docker_api_version(connection)
        path = f"/v{api_version}/containers/json?{urlencode({'filters': filters})}"
        containers = docker_json(connection, path)
    finally:
        connection.close()

    if not isinstance(containers, list):
        raise ValueError("Docker API did not return an array")

    names = set()
    for container in containers:
        if not isinstance(container, dict):
            raise ValueError("Docker API returned an invalid container")
        container_names = container.get("Names")
        if (
            not isinstance(container_names, list)
            or not container_names
            or not all(isinstance(name, str) and name for name in container_names)
        ):
            raise ValueError("Docker API returned a container without a name")
        normalized_names = [name.removeprefix("/") for name in container_names]
        if not all(normalized_names):
            raise ValueError("Docker API returned a container without a name")
        names.update(normalized_names)
    return sorted(names)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/unhealthy":
            self.send_error(404)
            return

        try:
            self.send_json(200, unhealthy_container_names())
        except Exception as error:
            self.log_error("Docker API request failed: %s", error)
            self.send_json(502, {"error": "Docker API request failed"})

    def send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
