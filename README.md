# Tender Intelligence Engine

Reads Indian power-sector tender documents into a structured, versioned record. Every value carries the page and quote it came from. A model proposes values; only a reviewer's approval makes them facts.

- Architecture: [docs/SOFTWARE-ARCHITECTURE.md](docs/SOFTWARE-ARCHITECTURE.md) (overview) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (the living, detailed version)
- Using it from TenderOS: [docs/TENDEROS-INTEGRATION-MANUAL.md](docs/TENDEROS-INTEGRATION-MANUAL.md)
- Connecting AI assistants and other products: [docs/CONNECTOR.md](docs/CONNECTOR.md)
- Rules for anyone changing the code: [CLAUDE.md](CLAUDE.md)

## Run it on your machine

You need Docker (Docker Desktop on macOS or Windows, Docker Engine with the compose plugin 2.24 or later on Linux), `make` and `git`. Nothing else: Python, Node and Postgres all run in containers.

```bash
git clone https://github.com/Ergplan/tender_engine.git
cd tender_engine
make local
```

The first run builds the images and takes 5 to 10 minutes. When it prints `ready`, open **http://localhost:8080** and sign in:

| | |
| --- | --- |
| Username | `admin` |
| Password | `admin-local-dev` |

These credentials only work on your machine. The app is bound to `127.0.0.1`, so nobody else on your network can reach it.

`make local` also loads a **demo tender**: a synthetic 600 MW solar RfS with one amendment, already read by a scripted model. You can explore the workspace, the review screen and the API without an Anthropic key or any spend. Its review link is printed at the end of `make local`.

### Reading real tenders

Reading a new tender calls Claude and costs real money, about USD 0.045 a page. To enable it, create `.env.local` in the repository root. It is gitignored, so it never gets committed.

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Then run `make local` again. Drop a PDF on the workspace at http://localhost:8080/workspace.

Scanned PDFs need the Docling OCR layer, which is off locally because it uses about 3 GB of memory. To turn it on, add `DOCLING_URL=http://docling:5001` to `.env.local` and run:

```bash
docker compose -p tender-engine-local -f docker-compose.yml -f infra/local/compose.yml --profile parsing up -d docling
```

### Everyday commands

| Command | Does |
| --- | --- |
| `make local` | Build, migrate, start and seed; safe to run again after a `git pull` |
| `make local-down` | Stop; your database and files are kept |
| `make local-reset` | Stop and delete the local database and files (start clean) |
| `make local-logs` | Follow the logs of every service |
| `make local-test` | Run the full Python and web test suites |
| `make local-watch` | Start the test watcher, which re-runs checks on every save |
| `make local-key NAME=tenderos` | Mint an API key on the local engine, for the workspace or a TenderOS build |

The code is mounted into the containers. The API reloads on save, and the web app hot-reloads in the browser.

### Ports and where things live

| What | Where |
| --- | --- |
| App, API and MCP | http://localhost:8080 (set `LOCAL_PORT` to change) |
| API reference | http://localhost:8080/api/v1/docs |
| Postgres | `localhost:5433`, user `tender`, password `tender` (set `LOCAL_DB_PORT` to change) |
| Uploaded files and page images | `./.local/data/` |
| Local settings | `infra/local/local.env` (checked in), overridden by `.env.local` (yours) |

### Pointing a local TenderOS at it

1. Run `make local-key NAME=tenderos` and copy the `secret` it prints.
2. In TenderOS, set `ENGINE_URL=http://localhost:8080` and `ENGINE_API_KEY=<secret>`.
3. If TenderOS runs in Docker, use `http://host.docker.internal:8080` instead.

Webhooks to private addresses are allowed locally (`WEBHOOK_ALLOW_PRIVATE=true`), so a receiver on your machine works.

### Troubleshooting

- **Port 8080 or 5433 is taken.** Run `LOCAL_PORT=8090 make local`. Also add `PUBLIC_BASE_URL=http://localhost:8090` to `.env.local`.
- **`!override` or `required` errors from compose.** Your Docker Compose is older than 2.24. Update Docker Desktop or the compose plugin.
- **Permission denied under `.local/` on Linux.** The containers run as uid 1000. Run `make local-reset`, then `make local`.

## Production

The deployed app runs on one GCE VM with `make deploy` (see `docs/HANDOVER.md`). `make local` never touches it: it uses its own compose project name, its own database volume and `./.local/`, and its seed script refuses to run unless the app's address is localhost.
