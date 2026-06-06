# GitHub Actions Production Deploy

> Updated: 2026-06-06

## Goal

Use GitHub Actions to deploy `main` to Tencent Cloud production while preserving runtime configuration files that are intentionally not owned by Git.

Production target:

- Host: `ubuntu@111.229.166.6`
- Path: `/home/ubuntu/marketing_bot`
- Branch: `main`
- Services:
  - `insightbot-web.service`
  - `insightbot-scheduler.service`

Workflow file:

- `.github/workflows/deploy-production.yml`

## Required GitHub Secrets

Configure these in GitHub:

`Settings -> Secrets and variables -> Actions -> Repository secrets`

Required:

- `TENCENT_HOST`: `111.229.166.6`
- `TENCENT_USER`: `ubuntu`
- `TENCENT_SSH_KEY`: private key content for the deploy SSH key

Optional:

- `TENCENT_SSH_PORT`: defaults to `22`
- `DEPLOY_PATH`: defaults to `/home/ubuntu/marketing_bot`

## Recommended GitHub Environment

Configure:

`Settings -> Environments -> New environment -> production`

Recommended protection:

- Add required reviewer approval before deployment.
- Keep the workflow `environment: production` so deployment can be manually approved after tests pass.

Without environment protection, every push to `main` will deploy automatically after tests pass.

## Deployment Behavior

The workflow runs in two jobs:

1. `test`
2. `deploy`

The `test` job:

- Installs `requirements.txt`
- Runs `PYTHONPATH=.:editorial-intelligence python -m pytest -q`
- Runs `python -m compileall insightbot scripts`

The `deploy` job SSHes into Tencent Cloud and runs the production-safe deploy flow:

1. Confirm production working tree is on `main`.
2. Backup runtime files into `/root/back-up/marketing_bot-deploy-snapshots/github-actions-*`.
3. Fetch `origin/main`.
4. Stop `insightbot-scheduler.service` and `insightbot-web.service`.
5. `git reset --hard origin/main`.
6. Restore runtime files:
   - `tasks.json`
   - `channels.json`
   - `config.content.json`
   - `config.secrets.json`
   - `.env`
   - `.env.local`
7. Run compile check on production.
8. Restart services.
9. Check service status and Streamlit HTTP response.

Manual workflow runs can set `run_dry_run=true` to execute:

```bash
./.venv/bin/python -m insightbot.cli --task Daily_brief --dry-run
```

## Runtime Config Boundary

Do not put production runtime config back into Git.

The deploy workflow deliberately restores runtime files after `git reset --hard origin/main`. This is required because production keeps environment-specific config and secrets outside Git.

If a future migration changes config ownership, update this document and `.github/workflows/deploy-production.yml` together.

## Failure Behavior

If deployment fails after services are stopped, the remote script attempts to restart:

- `insightbot-web.service`
- `insightbot-scheduler.service`

If a workflow fails, inspect:

- GitHub Actions logs
- `/root/back-up/marketing_bot-deploy-snapshots/`
- `systemctl status insightbot-web.service`
- `systemctl status insightbot-scheduler.service`
