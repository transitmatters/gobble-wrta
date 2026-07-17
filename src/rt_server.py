from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import gtfs_rt
import vehicle_snapshot
from logger import set_up_logging

logger = set_up_logging(__name__)

PORT = 8080

ROUTES = {
    "/vehiclepositions.pb": gtfs_rt.build_vehicle_positions,
    "/tripupdates.pb": gtfs_rt.build_trip_updates,
}


class RTRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        build_feed = ROUTES.get(self.path)
        if build_feed is None:
            self.send_error(404)
            return

        feed = build_feed(vehicle_snapshot.get_all_snapshots())
        body = feed.SerializeToString()

        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # browsers preflight cross-origin requests that carry custom headers/methods;
        # harmless to answer even if the client never sends one
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} " + format % args)


def _serve_forever():
    server = ThreadingHTTPServer(("", PORT), RTRequestHandler)
    logger.info(f"Serving GTFS-RT feeds on port {PORT}")
    server.serve_forever()


def start_server():
    server_thread = Thread(target=_serve_forever, name="rt_server")
    server_thread.start()
