# Sirens

A comprehensive, real-time web-based monitoring tool designed to track and report emergency events across Ukraine, including air raid alerts, threats of shelling, and explosions.

> **Disclaimer:** This project parses official Telegram channels to aggregate data about life-threatening situations (air raid alerts, shellings, etc.). As with any automated parsing pipeline, technical errors, delays, or service disruptions may occur. **This tool is NOT a replacement for official state emergency notification systems.** Rely on it at your own risk.

The system ingests real-time data from official Telegram channels, stores it in a robust relational database, and exposes it through both a RESTful API and a Live Threat Map.

## Key Features

* **Real-time Event Tracking:** Continuously monitors air raid alerts, artillery shelling threats, and local emergency events across all Ukrainian regions.
* **Telegram Integration:** Utilizes `Telethon` to parse official emergency notification channels with minimal latency.
* **RESTful API:** Provides structured JSON endpoints for consuming data regarding active threats across regions.
* **Live Threat Map:** A Flask-powered, dynamic GIS-based web interface built with **Leaflet** and **OpenStreetMap**, highlighting regions and cities under active air raid alerts or shelling threats in real-time.

## Architecture and Technology Stack

The project operates as a robust multi-container application comprising the following components:
* **Web Service (`web/`)**: A Flask web application served by Gunicorn, providing the user interface, GIS map rendering, and API endpoints.
* **Alerts Worker (`alerts/`)**: An asynchronous Python worker utilizing `Telethon` to monitor Telegram channels and process incoming alerts.
* **Subscriber Snapshot (`bi/`)**: A one-shot job that records how many subscribers each network channel has. Started by cron, not a long-running service.
* **Dashboard (`dashboard/`)**: An [Evidence](https://evidence.dev) project that turns those snapshots into a published site. Built in CI, hosted on Cloudflare Pages — it never runs on the server.
* **PostgreSQL**: The primary relational database used for reliable data storage.
* **Redis**: An in-memory data structure store, functioning as a message broker and state cache.

## Setup and Installation

The recommended method for deploying the Sirens project is via **Docker** and **Docker Compose**.

### Prerequisites
* Docker and Docker Compose installed on the host machine.
* Telegram API ID and Hash (obtainable from [my.telegram.org](https://my.telegram.org)).

### 1. Configuration
Create a `.env` file in the root directory of the project based on `.env.example`:
```env
# Telegram API Credentials
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# Application Mode (dev or prod)
APP_MODE=prod

# Flask Secret Key
FLASK_SECRET_KEY=your_secure_random_string

# PostgreSQL Credentials (Required for Docker)
POSTGRES_USER=admin
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=sirens
```

*Note: Redis is configured automatically via the internal Docker network (`REDIS_URL` is set to `redis://redis:6379/0` inside `docker-compose.yml`), so it requires no additional variables in the `.env` file.*

### 2. Deployment via Docker Compose
To build and initialize all services (PostgreSQL, Redis, Web App, Alerts Worker) in detached mode, execute the following command:
```bash
docker-compose up -d --build
```

The web interface will subsequently be accessible at `http://localhost:8000`.

### 3. Managing the Application (Docker Commands)

Once the application is running, you can manage it using the following commands:

* **View Logs:** Monitor the output of all services in real-time.
  ```bash
  docker-compose logs -f
  ```
  *(To view logs for a specific service, append its name, e.g., `docker-compose logs -f web`)*

* **Check Status:** See the status of running containers.
  ```bash
  docker-compose ps
  ```

* **Stop the Application:** Stop the running containers without removing data.
  ```bash
  docker-compose stop
  ```

* **Shut Down & Remove:** Stop the containers and remove them entirely.
  ```bash
  docker-compose down
  ```

## RESTful API Usage

The application provides a public RESTful API endpoint at `/api` that returns a structured JSON map of all regions and their current threat statuses.

**Endpoint:** `GET /api`

**Example Response:**
```json
{
  "kyiv": {
    "alert": {
      "status": 1,
      "time": "14:23",
      "source": "https://t.me/channel/123"
    },
    "explosion": {
      "status": 0,
      "time": "None",
      "source": "None"
    }
  },
  "kherson": {
    "alert": {
      "status": 0,
      "time": "None",
      "source": "None"
    },
    "explosion": {
      "status": 1,
      "time": "12:10",
      "source": "https://t.me/channel/456"
    },
    "shelling": {
      "status": 1,
      "time": "12:05",
      "source": "https://t.me/channel/455"
    }
  }
}
```

**Schema Details:**
* The `alert` and `explosion` objects are guaranteed to be present for **all** regions in the response.
* The `shelling` (artillery shelling threat) object is present only for cities near the front line where shelling monitoring is enabled
* `status`: `1` (Active) or `0` (Inactive)
* `time`: Time of the event formatted as `HH:MM` in the **Kyiv timezone (`Europe/Kyiv`)**, or `"None"` if not applicable.
* `source`: URL to the Telegram message source (if available) or `"None"`

## Channel Statistics

The project tracks how many subscribers the network has. A snapshot counts every
channel once a day and stores one row per channel per day in `channel_stats`;
a dashboard renders the result.

### Collecting

The snapshot is a one-shot process, not a service — it counts, writes, and exits,
so it holds no memory between runs. Scheduling is cron's job.

It logs in to Telegram under its own session, because the alerts worker already
holds `sirens.session` and one session file cannot serve two running processes:

```bash
./deploy/setup.sh bi        # one-time interactive login, creates bi.session
./deploy/bi.sh              # run it once by hand to check
```

Then schedule it:

```
0 9 * * * cd /sirens && ./deploy/bi.sh >> logs/bi.log 2>&1
```

Re-running on the same day is safe: it overwrites that day's rows instead of
adding duplicates.

### Publishing

`GET /bi/stats.csv` exports the table as CSV. **This endpoint is not public**:
it is guarded by the `X-Stats-Token` header, whose value comes from
`STATS_EXPORT_TOKEN` in `.env`. Leaving that variable unset removes the route
entirely.

The [dashboard](dashboard/) is built from that CSV by
`.github/workflows/dashboard.yml` and published to Cloudflare Pages once a day.
Nothing in this path touches the server beyond a single HTTP request, and the
published site is kept behind Cloudflare Access.

## License

This project is licensed under the PolyForm Strict License 1.0.0. See the [LICENSE](LICENSE) file for details.