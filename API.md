# Coln River Guardians Dashboard — Private API

This API allows external sites to request and retrieve water quality reports. All requests require authentication via an API key.

## Authentication

Include an `api_key` query parameter on every request:

```
?api_key=YOUR_API_KEY
```

## Managing API Keys (Admin Only)

The admin key is stored as `ADMIN_API_KEY` in `/etc/environment` on the main droplet. Only the dashboard owner has access.

### Generate a new API key

```bash
curl -X POST "https://161.35.168.168/api/v1/admin/keys/generate?admin_key=ADMIN_KEY&label=my-app"
```

### List all API keys

```bash
curl "https://161.35.168.168/api/v1/admin/keys/list?admin_key=ADMIN_KEY"
```

### Revoke an API key

```bash
curl -X POST "https://161.35.168.168/api/v1/admin/keys/revoke?admin_key=ADMIN_KEY&key_id=ID"
```

## Endpoints

### Get the latest report for a site

```
GET /api/v1/reports/site?site=PW&api_key=YOUR_KEY
```

Returns the full report text, version, and generation timestamp for the given site.

**Response:**
```json
{
  "id": 8,
  "site_code": "PW",
  "generated_at": "2026-05-27T17:26:56.207101+00:00",
  "report_text": "...",
  "version": 8
}
```

### Get the latest report for a round

```
GET /api/v1/reports/round?round_label=Round%206&api_key=YOUR_KEY
```

Returns the full report text for the given round label.

### Trigger a new site report

```
POST /api/v1/reports/site/generate?site=PW&api_key=YOUR_KEY
```

Queues a new report generation for the site. Returns immediately with a task ID.

**Response:**
```json
{
  "status": "queued",
  "site": "PW",
  "task_id": "site_PW"
}
```

Reports take 2–5 minutes to generate (droplet spin-up + LLM inference). Poll the GET endpoint to retrieve the report once ready.

### Trigger a new round report

```
POST /api/v1/reports/round/generate?round_label=Round%206&round_start=2026-03-01&round_end=2026-03-31&api_key=YOUR_KEY
```

## Quick Reference

| What | Command |
|---|---|
| Get PW site report | `curl "https://161.35.168.168/api/v1/reports/site?site=PW&api_key=KEY"` |
| Get Round 6 report | `curl "https://161.35.168.168/api/v1/reports/round?round_label=Round%206&api_key=KEY"` |
| Generate PW report | `curl -X POST "https://161.35.168.168/api/v1/reports/site/generate?site=PW&api_key=KEY"` |
| Generate Round 6 report | `curl -X POST "https://161.35.168.168/api/v1/reports/round/generate?round_label=Round%206&round_start=2026-03-01&round_end=2026-03-31&api_key=KEY"` |
