# Security

Agent2Chat lets a chat message drive a coding agent on your machine. Treat it like
remote shell access, because effectively it is.

## Threat model & controls

- **Allow-list.** Only user ids in `allowed_user_ids` can drive the agent. An empty
  list means the bot refuses everyone. Use `/id` to discover your own id.
- **No shell injection.** Agents run via `subprocess` with an argv list (never
  `shell=True`), so message text cannot inject shell syntax.
- **Hard timeout.** Each agent run is killed after `agent_timeout` seconds.
- **Secrets at rest.** The config file holds tokens; it is written `0600` inside a
  `0700` directory and never logged in full. Prefer environment variables
  (`TELEGRAM_BOT_TOKEN`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `TEAMS_APP_ID`,
  `TEAMS_APP_PASSWORD`, `TEAMS_TENANT_ID`) to keep secrets out of the file entirely.

## Platform notes

- **Telegram / Slack** use outbound connections (long polling / Socket Mode), so no
  inbound port is exposed.
- **Teams** runs an inbound HTTP webhook (`/api/messages`). Always place it behind
  HTTPS (reverse proxy, Azure App Service, or a dev tunnel) and restrict network access.
  The allow-list still gates who can drive the agent, but you should additionally
  validate the Bot Framework JWT at your proxy or extend the connector to do so before
  exposing it on an untrusted network.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository, or contact the
SLOnline maintainers directly. Do not file public issues for vulnerabilities.
