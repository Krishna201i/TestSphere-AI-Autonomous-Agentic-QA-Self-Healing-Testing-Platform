# Deploying on AWS EC2

One EC2 instance runs three containers from [`docker-compose.yml`](docker-compose.yml):

| Container | Role |
| --- | --- |
| `api` | API and the built dashboard, behind Caddy (port 8000 is not published) |
| `worker` | Pipeline runs (`PIPELINE_EXECUTION=worker`) and the scheduler, so an API restart never interrupts a scan |
| `caddy` | HTTPS on 80/443 with an automatic Let's Encrypt certificate for `$DOMAIN` |

Firestore is the shared database (worker mode requires it). Both app containers run with
`ENGINE_MAX_BROWSERS=1`, sized for a 2 GB instance; raise it on a larger one.

## Secrets

Secrets live in SSM Parameter Store under `/testsphere/` as SecureStrings, never in the repository.

- [`store-secrets.py`](store-secrets.py) (run locally) writes them from your `.env`; `FIREBASE_CREDENTIALS` may be a path to the service-account JSON.
- [`fetch-env.sh`](fetch-env.sh) (run on the instance) reads them with the instance role into `/opt/testsphere/secrets.env` (mode 600).

To add a secret, add its name to `KEYS` in `store-secrets.py`, run it, then rerun `fetch-env.sh` and `docker compose up -d` on the instance.

## Instance setup

- Ubuntu 24.04, an encrypted gp3 disk, 2 GB swap, Docker and the Compose plugin, the repository cloned to `/opt/testsphere/app`.
- Security group: inbound 80 and 443 only. There is no SSH. The instance is managed with **AWS Systems Manager** (Run Command / Session Manager) over HTTPS, so it also works from networks that block port 22.
- Instance role: `AmazonSSMManagedInstanceCore`, plus read access to `parameter/testsphere/*` only.
- IMDSv2 required; t3 CPU credits on *standard*, so bursts throttle instead of billing extra.
- `deploy/aws-ec2/.env` on the instance holds `DOMAIN=<elastic-ip-with-dashes>.sslip.io`, or your own domain once DNS points at the Elastic IP.

## Updating

Run on the instance (Session Manager, or `AWS-RunShellScript` through Run Command):

```sh
cd /opt/testsphere/app && git pull --ff-only
cd deploy/aws-ec2 && ./fetch-env.sh && docker compose up -d --build
docker compose ps
```

Rollback: `git checkout <previous-sha>` in `/opt/testsphere/app`, then `docker compose up -d --build` again.

## Checking

```sh
docker compose ps                       # all three Up; api (healthy)
docker compose logs --tail 50 api worker
curl -s https://$DOMAIN/api/health      # {"status":"ok",...,"database":"ok"}
```

After the first deploy, add the domain to Firebase → Authentication → Settings → Authorised domains. The API serves
the dashboard on the same origin, so `VITE_API_URL` and `CORS_ORIGINS` stay unset.

## Moving from another host

Copy the old host's environment variables into a file (for example `old-host.env`, kept out of git), then run
`python deploy/aws-ec2/store-secrets.py --env-file old-host.env --all` and reload on the instance. Keep
`TOKEN_ENCRYPTION_KEY` unchanged: GitHub tokens already in Firestore were encrypted with it.
