from poll_loop import poll_vehicles_forever
from gtfs import start_watching_gtfs
from rt_server import start_server
from topology import start_watching_topology


def main():
    start_watching_gtfs()
    start_watching_topology()
    start_server()
    poll_vehicles_forever()


if __name__ == "__main__":
    main()
