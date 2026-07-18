# gobble-wrta

gobble-wrta adapts TransitMatters' [gobble](https://github.com/transitmatters/gobble) for the Worcester Regional Transit Authority bus network. WRTA doesn't expose a standard real-time GTFS feed, so this project reads their CAD/AVL API instead and republishes bus arrivals in formats that existing transit tooling already understands:

- CSV output matching the format used by the [TransitMatters Data Dashboard](https://github.com/transitmatters/t-performance-dash)
- A GTFS Realtime stream

## How it works

WRTA does publish an official GTFS Realtime feed, but it only carries service alerts -- no trip updates or vehicle positions. gobble-wrta fills that gap by polling WRTA's CAD/AVL API for live vehicle positions and next-stop info, matching each vehicle against its GTFS route/trip/stop, and recording arrival and departure events from the result.

### GTFS Realtime coverage

Support for the spec is partial so far:

**Trip updates** -- trip info (trip/route/direction), and a single stop time update for the immediate next stop.

**Vehicle positions** -- vehicle ID, latitude/longitude, speed, current stop sequence, stop ID, timestamp, occupancy, and trip info.

Not yet supported: trip start time, schedule relationship, vehicle license plate, vehicle odometer, congestion level, and occupancy status.

## Requirements to develop locally

- [`uv`](https://docs.astral.sh/uv/) with Python 3.13
  - Ensure `uv` is using the correct Python version by running `uv venv --python 3.13`

## Development Instructions

1. In the root directory, run `uv sync` to install dependencies.
2. Run `uv run src/gobble.py` to start.
3. Output will be in `data/` in your current working directory.

## Running with Docker

1. Build the image: `docker build -t gobble-wrta .`
2. Run it: `docker run -p 8080:8080 gobble-wrta`

## Deploying to production

`docker-compose.yml` runs gobble-wrta alongside a Caddy front door that reverse-proxies the GTFS-RT feed (`/vehiclepositions.pb`, `/tripupdates.pb`) and serves `data/daily-bus-data/` read-only for browsing/download.

To stand up a fresh DigitalOcean droplet from this config:

```
doctl compute droplet create gobble-wrta-prod \
  --image ubuntu-24-04-x64 \
  --size s-1vcpu-1gb \
  --region nyc3 \
  --ssh-keys <your-ssh-key-fingerprint> \
  --user-data-file cloud-init.yml
```

`cloud-init.yml` installs Docker, clones this repo, and runs `docker compose up -d` on first boot -- no manual SSH setup required. If you point a domain at the droplet, replace `:80` in the `Caddyfile` with that domain and Caddy will provision HTTPS automatically.

## Support TransitMatters

If you've found this app helpful or interesting, please consider [donating](https://transitmatters.org/donate) to TransitMatters to help support our mission to provide data-driven advocacy for a more reliable, sustainable, and equitable transit system in Metropolitan Boston.
