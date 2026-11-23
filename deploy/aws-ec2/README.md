# Deploying on AWS EC2

One EC2 instance runs four containers from two images (the **backend** and the **frontend**), with
[`docker-compose.yml`](docker-compose.yml):

```
internet ─▶ caddy :443 ─▶ frontend :8080 ─┬─ dashboard files (nginx)
                                          └─ /api ─▶ backend :8000      worker (same image as backend)
```

| Container | Image | Role |
| --- | --- | --- |
| `caddy` | `caddy` | HTTPS on 80/443 with an automatic Let's Encrypt certificate for `$DOMAIN`; the only published ports |
| `frontend` | `testsphere-frontend` ([`frontend/Dockerfile`](../../frontend/Dockerfile)) | The dashboard on nginx; proxies `/api` to the backend |
| `backend` | `testsphere` ([`backend/Dockerfile`](../../backend/Dockerfile)) | The API (port 8000, reachable only from the frontend) |
| `worker` | `testsphere` (same as `backend`) | Pipeline runs (`PIPELINE_EXECUTION=worker`) and the scheduler, so an API restart never interrupts a scan |

Firestore is the shared database (worker mode requires it). The backend and worker run with
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
  It may also hold `SECURITY_ACTIVE_SCAN_USERS=<firebase-uid>,…` to narrow active (DAST) scans to those accounts. Without it, any account may actively scan the sites whose ownership it verified (Security → Sites for active testing).

## Artifacts in S3 (optional)

By default screenshots, DOM snapshots and traces stay in the `testsphere-data` volume, so they go if the disk
does. To keep them in S3 instead, once (in the project's selected Region, ap-southeast-2 here; check it in
AWS Settings > View all projects > Overview > Additional Info > Region):

```sh
BUCKET=testsphere-artifacts-$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --bucket "$BUCKET" --region ap-southeast-2     --create-bucket-configuration LocationConstraint=ap-southeast-2
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration     BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
# Let the instance role use only that bucket (ROLE = the instance role's name)
sed "s/BUCKET/$BUCKET/" deploy/aws-ec2/artifacts-role-policy.json > /tmp/artifacts-policy.json
aws iam put-role-policy --role-name ROLE --policy-name testsphere-artifacts     --policy-document file:///tmp/artifacts-policy.json
```

Then add `ARTIFACT_STORE=s3` and `ARTIFACT_BUCKET=<bucket>` to this folder's `.env` on the instance and run
`docker compose up -d`. The app applies `ARTIFACT_RETENTION_DAYS` as a lifecycle rule on `testsphere-artifacts/`.
New buckets are encrypted (SSE-S3) by default. Artifacts already in the volume stay there until they expire.

## Disk and logs

Container logs are capped at 3 × 10 MB each (`logging:` in the compose file), and artifacts expire after
`ARTIFACT_RETENTION_DAYS`. A daily timer removes the Docker images and build cache every rebuild leaves behind,
and any leftover repository checkouts ([`housekeeping.sh`](housekeeping.sh)). Install it once:

```sh
sudo cp /opt/testsphere/app/deploy/aws-ec2/testsphere-housekeeping.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now testsphere-housekeeping.timer
systemctl list-timers testsphere-housekeeping.timer   # next run
```

Run it by hand with `sudo systemctl start testsphere-housekeeping` (output: `journalctl -u testsphere-housekeeping`).

## Backups and alarms

[`monitoring/setup.sh`](monitoring/setup.sh), run once from your machine with the AWS CLI
(`deploy/aws-ec2/monitoring/setup.sh <instance-id> <alert-email>`), sets up:

- **Snapshots:** daily snapshots of the instance's disks (Data Lifecycle Manager), the 7 newest kept. They hold the
  artifacts volume, Caddy's certificates and the `.env` files; secrets are in SSM anyway. To restore, create a volume
  from a snapshot (EC2 → Snapshots) and swap it in, or launch a new instance from it.
- **Alarms to your email (SNS):** a failed system check recovers the instance, a failed instance check reboots it,
  and disk over 80 %, memory over 90 % or a CPU credit balance under 20 (a *standard* t3 slows down when it runs
  out) send an alert.

Disk and memory come from the CloudWatch agent. Give the instance role the managed policy
`CloudWatchAgentServerPolicy`, then install and configure the agent over SSM:

```sh
aws ssm put-parameter --name AmazonCloudWatch-testsphere --type String --overwrite     --value file://deploy/aws-ec2/monitoring/cloudwatch-agent.json
aws ssm send-command --instance-ids INSTANCE_ID --document-name AWS-ConfigureAWSPackage     --parameters action=Install,name=AmazonCloudWatchAgent
aws ssm send-command --instance-ids INSTANCE_ID --document-name AmazonCloudWatch-ManageAgent     --parameters action=configure,mode=ec2,optionalConfigurationSource=ssm,optionalConfigurationLocation=AmazonCloudWatch-testsphere,optionalRestart=yes
```

**Firestore** is backed up on Google's side: `gcloud firestore backups schedules create --database='(default)'
--recurrence=daily --retention=7d` (needs the Blaze plan).

Costs: about $1–2 a month (2 agent metrics, 5 alarms, incremental snapshots); `aws freetier
get-account-plan-state` shows whether the project is on the free or paid plan.

## Continuous deployment

Pull-based, so no AWS credentials leave AWS (this AWS project's managed policies do not allow GitHub to
federate into the account with OIDC, and a long-lived access key in GitHub would be the weaker option):

1. [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) runs after CI passes on `main`. It builds
   both images and publishes them to GitHub's container registry, with the workflow's own token:
   `ghcr.io/krishna201i/testsphere` (backend) and `ghcr.io/krishna201i/testsphere-frontend`, each as `:<commit>`,
   `:<short commit>` and `:main`. The backend's `:main` moves last. Nothing builds on the instance.
2. On the instance, `testsphere-deploy.timer` runs [`cd/pull-deploy.sh`](cd/pull-deploy.sh) every 2 minutes. When
   the backend's `:main` points at a new image it checks out that commit (for its compose file and Caddyfile), pulls
   the frontend image of **the same commit**, starts both, and waits for `https://$DOMAIN/api/health` (through
   Caddy, the frontend and the backend, so all three must work). If the new version is not healthy within 5
   minutes, it puts the previous images and commit back. Log: `journalctl -u testsphere-deploy`.

The instance pulls without a token, so both packages must be **public**. GitHub creates a new package as
private, so the first run that publishes `testsphere-frontend` stops before moving `:main` (the instance keeps
running the current version) and says so. Then, once: the repository owner's Packages → `testsphere-frontend` →
Package settings → Change visibility → Public, and re-run the failed Deploy run.

It stays off until the repository variable `DEPLOY_ENABLED` is `true`. One-time setup on the instance (as root,
for example through SSM Run Command):

```sh
git config --global --add safe.directory /opt/testsphere/app
cd /opt/testsphere/app && git fetch -q origin && git checkout -q --detach origin/main
install -m 644 deploy/aws-ec2/cd/testsphere-deploy.service deploy/aws-ec2/cd/testsphere-deploy.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now testsphere-deploy.timer
```

**Rollback:** Actions → Deploy → Run workflow with the earlier commit. Its image is republished as `:main` (not
rebuilt) and the instance rolls to it within a few minutes.

## Updating by hand

Without CD, run on the instance (Session Manager, or `AWS-RunShellScript` through Run Command):

```sh
cd /opt/testsphere/app && git fetch && git checkout --detach origin/main
cd deploy/aws-ec2 && ./fetch-env.sh && GIT_COMMIT=$(git rev-parse --short=7 HEAD) docker compose up -d --build
docker compose ps
```

Rollback: `git checkout --detach <previous-sha>` in `/opt/testsphere/app`, then the same `docker compose` command.
Once CD has run, `TESTSPHERE_IMAGE` and `TESTSPHERE_FRONTEND_IMAGE` in this folder's `.env` point at the published
ghcr.io images; delete those lines to build both on the instance again.

## Checking

```sh
docker compose ps                       # all four Up; backend, worker and frontend (healthy)
docker compose logs --tail 50 backend worker frontend
curl -s https://$DOMAIN/api/health      # {"status":"ok",...,"database":"ok","queued":0,"worker":"ok"}
```

After the first deploy, add the domain to Firebase → Authentication → Settings → Authorised domains. The frontend
container serves the dashboard and proxies the API on the same origin, so `VITE_API_URL` and `CORS_ORIGINS` stay unset.

## Moving from another host

Copy the old host's environment variables into a file (for example `old-host.env`, kept out of git), then run
`python deploy/aws-ec2/store-secrets.py --env-file old-host.env --all` and reload on the instance. Keep
`TOKEN_ENCRYPTION_KEY` unchanged: GitHub tokens already in Firestore were encrypted with it.
