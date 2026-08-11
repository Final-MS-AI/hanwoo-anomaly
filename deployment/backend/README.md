# Backend VM deployment snapshot

This directory records the deployment configuration currently used by the
Azure VM at `hanwoo.koreacentral.cloudapp.azure.com`.

## Files

- `Caddyfile`: public HTTPS routes for the frontend, FastAPI backend, and
  muzzle identification API.
- `hanwoo-fastapi.service`: systemd unit for the main backend on port 8000.

The service loads runtime secrets from
`/home/azureuser/3rd_fastapi/.env`. That file is intentionally not committed.

## Install

```bash
sudo cp deployment/backend/Caddyfile /etc/caddy/Caddyfile
sudo cp deployment/backend/hanwoo-fastapi.service \
  /etc/systemd/system/hanwoo-fastapi.service
sudo systemctl daemon-reload
sudo systemctl restart hanwoo-fastapi
sudo systemctl reload caddy
```

Review server paths and the Linux user before applying this snapshot to a
different VM.
