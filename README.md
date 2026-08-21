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
* **Dashboard (`dashboard/`)**: An [Evidence](https://evidence.dev) project that turns those snapshots into a published site. Built in CI, served from Cloudflare R2 by a small Worker — it never runs on the server.
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
* `source`: URL of the broadcast message in that city's Telegram channel (e.g. `https://t.me/kyiv_alert/512`), so the map can link a pill straight to it. Falls back to `"telegram"` for events recorded before message links were stored or whose link could not be resolved, and `"None"` when there is no event at all.

## Channel Statistics

The project tracks how many subscribers the network has. A snapshot counts every
channel periodically (e.g. every 4 hours) and stores snapshot rows with timestamps
in `subscribers`; a dashboard renders the result.

### Collecting

The snapshot is a one-shot process, not a service — it counts, writes, and exits,
so it holds no memory between runs. Scheduling is cron's job.

It logs in to Telegram under its own session, because the alerts worker already
holds `sirens.session` and one session file cannot serve two running processes:

```bash
./deploy/setup.sh bi        # one-time interactive login, creates bi.session
./deploy/bi.sh              # run it once by hand to check
```

Then schedule it (e.g. every 4 hours):

```
0 */4 * * * cd /sirens && ./deploy/bi.sh >> logs/bi.log 2>&1
```

Re-running is safe: it updates existing rows for the snapshot timestamp instead of
adding duplicates.

A run that reaches fewer than 90% of the channels is **discarded rather than
stored**, and exits non-zero so the healthcheck fires. Summed across the
network, a short run looks exactly like subscribers walking away, while a gap
in the chart is visibly a gap — and re-running fills the data in once the cause
is fixed.

### Publishing

After recording the subscriber snapshot, the BI worker exports the consolidated history as CSV directly to the Cloudflare R2 data bucket (`s3://sirens-bi-data/subscribers.csv`) and optionally triggers GitHub Actions via `workflow_dispatch`.

The [dashboard](dashboard/) is built from that CSV by `.github/workflows/dashboard.yml` and synced into the public Cloudflare R2 web bucket (`sirens-bi-web`). Nothing in this build path touches the production web server.

It is **not** on Cloudflare Pages: Pages rejects any file over 25 MiB and Evidence bundles a 32.7 MiB `duckdb-eh.wasm`. R2 has no such limit, but it also serves objects by exact key — so [`dashboard/worker`](dashboard/worker) maps request paths to keys, resolves `index.html`, sets content types and passes range requests through.

One-time setup, in order:

1. Create the R2 buckets `sirens-bi-data` (private data bucket) and `sirens-bi-web` (public web bucket). They live in the **EU** jurisdiction, which changes the S3 endpoint host (`<id>.eu.r2...`).

   picking a different one means a new bucket and matching edits in
   `dashboard/worker/wrangler.toml` and the workflow's `R2_ENDPOINT`.
2. Create an R2 API token with **Object Read & Write** on that bucket — the sync
   runs with `--delete`, which read-only permissions refuse. Take it from
   **R2 → API → Manage API tokens**, which hands you a ready Access Key ID and
   Secret Access Key (shown once). A general account API token is not
   interchangeable: there the key id is the token's `id` and the secret is the
   SHA-256 of its value, so pasting the token string itself just fails to sign.
   Store the pair as the `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` GitHub
   secrets and in the server's `.env`, alongside `CLOUDFLARE_ACCOUNT_ID`.
3. Deploy the Worker: `cd dashboard/worker && npx wrangler deploy`.
4. Attach the custom domain to the **Worker** (Workers & Pages → `sirens-bi` →
   Settings → Domains & Routes).
5. Put Cloudflare Access in front of that hostname. A built Evidence site ships
   the whole dataset to the browser and has no login of its own.


CI only syncs files into the bucket; the Worker is deployed by hand and changes
roughly never.

## License

This project is licensed under the PolyForm Strict License 1.0.0. See the [LICENSE](LICENSE) file for details.