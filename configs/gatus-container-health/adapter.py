import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit

DOCKER_HOST = urlsplit(
    os.environ.get("DOCKER_HOST", "tcp://docker-socket-proxy-read:2375")
)
COMPOSE_PROJECT_NAME = os.environ["COMPOSE_PROJECT_NAME"]
DOCKER_TIMEOUT = 5


def unhealthy_container_names():
    filters = json.dumps(
        {
            "health": ["unhealthy"],
            "label": [f"com.docker.compose.project={COMPOSE_PROJECT_NAME}"],
        },
        separators=(",", ":"),
    )
    path = f"/containers/json?{urlencode({'filters': filters})}"
    connection = http.client.HTTPConnection(
        DOCKER_HOST.hostname,
        DOCKER_HOST.port,
        timeout=DOCKER_TIMEOUT,
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Docker API returned {response.status}")
        containers = json.load(response)
    finally:
        connection.close()

    if not isinstance(containers, list):
        raise ValueError("Docker API did not return an array")

    names = set()
    for container in containers:
        container_names = container.get("Names")
        if not container_names:
            raise ValueError("Docker API returned a container without a name")
        names.update(name.removeprefix("/") for name in container_names)
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
