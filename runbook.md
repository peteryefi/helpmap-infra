# Helpmap Testbed — Operations Runbook

Reference commands for operating the `helpmap-infra` CDK stacks and the
services they deploy. All AWS CLI/CDK commands assume the `helpmap` profile
(IAM Identity Center / SSO) and `us-west-2` region unless noted.

## Quick reference

| Thing | Value |
|---|---|
| AWS profile | `helpmap` |
| Region | `us-west-2` |
| API domain | `api-testbed.helpmap.us` |
| PWA domain | `testbed.helpmap.us` |
| API stack | `Helpmap-testbed-Api` |
| PWA stack | `Helpmap-testbed-Pwa` |
| GitHub secret | `helpmap/github-token` |
| Mapbox secret | `helpmap/mapbox-token` |
| SSH user | `ubuntu` |
| SSH key | Lightsail console → Account → SSH keys → download default key |

The Lightsail static IP and Amplify App ID are environment-specific — check
current values with the commands in the relevant sections below rather than
hardcoding them here, since either can change (e.g. after an instance
resize).

---

## 1. AWS / CDK authentication

SSO sessions expire (commonly every 8–12h). Re-authenticate with:

```bash
aws sso login --profile helpmap
aws sts get-caller-identity --profile helpmap   # sanity check
```

`cdk bootstrap` is a one-time per-account/region setup — already done for
this account/region. No need to re-run it for new stacks.

---

## 2. CDK commands

```bash
cd helpmap-infra
source .venv/bin/activate

cdk list                                        # see all stack names
cdk synth <StackName>                           # render CFN template, review before deploying
cdk diff <StackName> --profile helpmap           # ALWAYS review before deploy
cdk deploy <StackName> --profile helpmap
cdk deploy --all --profile helpmap               # deploys both stacks; unchanged ones no-op safely
```

`cdk deploy`/`diff` need `--profile helpmap` on every invocation — it is not
remembered between commands.

---

## 3. Reports API (Lightsail) — SSH access

```bash
chmod 400 <key.pem>
ssh -i <key.pem> ubuntu@<static-ip>
```

If SSH refuses with `Host key verification failed` (happens after the
instance is replaced, e.g. a resize — same IP, new machine, new host key):

```bash
ssh-keygen -R <static-ip>
# reconnect, type "yes" when prompted to trust the new key
```

---

## 4. Reports API — first-time instance setup

```bash
sudo apt update && sudo apt install -y python3.12-venv python3-pip nginx certbot python3-certbot-nginx git
```

Always run `apt update` before `apt install` on a fresh instance — skipping
it causes `E: Package 'python3.12-venv' has no installation candidate` even
though the package exists.

Clone the repo (HTTPS is simplest on a box with no SSH key registered to
GitHub):

```bash
git clone https://YOUR_PAT@github.com/peteryefi/helpmap-reports-api.git
```

Deploy:

```bash
cd helpmap-reports-api
bash deploy/deploy.sh
```

`deploy.sh` clones/pulls, creates the venv if missing, installs deps,
creates `.env` from `.env.example` if missing, installs the systemd unit,
and restarts the service. Safe to re-run for redeploys.

**After a fresh `.env` is created, these values do NOT carry over from any
previous instance and must be re-set manually:**

```bash
# generate + append the admin delete token in one step
echo "ADMIN_DELETE_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env

# edit CORS_ORIGINS to match the live PWA domain(s), e.g.:
# CORS_ORIGINS=https://testbed.helpmap.us,https://main.<amplify-app-id>.amplifyapp.com

sudo systemctl restart helpmap-api
sudo systemctl status helpmap-api
```

`Settings` is cached (`@lru_cache`) and only reads `.env` at process
startup — a restart is required after any `.env` change, `git pull` alone
never picks it up.

---

## 5. Reports API — nginx + TLS

```bash
sudo cp ~/helpmap-reports-api/deploy/nginx.conf /etc/nginx/sites-available/helpmap-api
sudo nano /etc/nginx/sites-available/helpmap-api   # confirm: server_name api-testbed.helpmap.us;

sudo ln -s /etc/nginx/sites-available/helpmap-api /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default        # CRITICAL — see troubleshooting below
sudo nginx -t && sudo systemctl reload nginx

curl -s http://api-testbed.helpmap.us/health       # verify HTTP works before adding TLS

sudo certbot --nginx -d api-testbed.helpmap.us
curl -s https://api-testbed.helpmap.us/health
```

nginx's default body-size limit is 1MB, which would silently 413-reject a
report carrying a base64-encoded photo; `deploy/nginx.conf` raises
`client_max_body_size` to 10MB to comfortably exceed
`MAX_PHOTO_BASE64_CHARS` in `app/config.py` (8,000,000 chars ≈ 6MB of image
data) plus JSON envelope overhead.

---

## 6. Reports API — DNS (Squarespace)

A record: Host `api-testbed`, Type `A`, Data = the static IP.

**Squarespace gotcha:** the Host field only takes the portion *before*
`.helpmap.us` — Squarespace appends the root domain automatically. Entering
the full name (even with just the trailing dot stripped) creates a wrong,
doubled record.

```bash
dig api-testbed.helpmap.us   # verify propagation
```

---

## 7. Reports API — database backup / restore

**Backup** (run from your laptop):

```bash
scp -i <key.pem> \
  ubuntu@<static-ip>:~/helpmap-reports-api/data/reports.db \
  ./reports-backup-$(date +%Y-%m-%d).db
```

**Restore** — stop the service first; swapping the file under a live SQLite
connection is unsafe:

```bash
# on the instance
sudo systemctl stop helpmap-api

# from your laptop
scp -i <key.pem> \
  ./reports-backup-YYYY-MM-DD.db \
  ubuntu@<static-ip>:~/helpmap-reports-api/data/reports.db

# on the instance
sudo systemctl start helpmap-api
curl -s https://api-testbed.helpmap.us/reports | head -c 500   # confirm data is back
```

---

## 8. Reports API — resizing the Lightsail instance

`BundleId` on `AWS::Lightsail::Instance` does **not** support in-place
CloudFormation updates or automatic replacement ("Updates are not
supported"). Resizing requires forcing a new logical resource:

1. Check available bundles: `aws lightsail get-bundles --profile helpmap --region us-west-2`
2. **Back up the database first** (section 7) — the old instance's disk is
   destroyed.
3. In `config.py`, update the testbed entry: `lightsail_bundle_id="micro_3_0"` (or target size)
4. In `testbed_api_stack.py`, rename to force replacement:
   - `instance_name = f"helpmap-{config.env_name}-api-v2"`
   - `CfnInstance(self, "ApiInstanceV2", ...)` (bump the logical id)
   - `CfnStaticIp` does **not** need renaming — `AttachedTo` supports an
     in-place update (confirmed via CFN docs: "Update requires: No
     interruption"), and it already reads the same `instance_name` variable.
5. `cdk diff Helpmap-testbed-Api --profile helpmap` — confirm exactly:
   old instance **removed**, new instance **added**, static IP shown as an
   **update** (not replaced).
6. `cdk deploy Helpmap-testbed-Api --profile helpmap`

   **This causes a real outage.** CloudFormation creates the new (blank)
   instance, re-points the static IP to it, then deletes the old one — the
   API goes down the moment the IP switches, until the new box is fully
   re-set-up. Do this only when you have time to immediately complete the
   next step.
7. Fix the SSH host key (section 3), then redo the **entire** first-time
   setup on the new instance: sections 4, 5, and restore the DB (section 7)
   — a resize produces a genuinely blank Ubuntu box.

**Mitigation for RAM pressure short of a full resize** — add a swap file
(non-destructive, no downtime, doesn't fix root cause but prevents a hard
freeze under a burst):

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirm Swap line shows 1.0Gi
```

---

## 9. PWA (Amplify) — secrets

```bash
aws secretsmanager create-secret --name helpmap/github-token --secret-string "ghp_..." --profile helpmap --region us-west-2
aws secretsmanager create-secret --name helpmap/mapbox-token --secret-string "pk...." --profile helpmap --region us-west-2

# update an existing secret's value
aws secretsmanager update-secret --secret-id helpmap/mapbox-token --secret-string "pk_NEW_VALUE" --profile helpmap --region us-west-2

# read a secret's current value (prints to terminal — don't paste elsewhere)
aws secretsmanager get-secret-value --secret-id helpmap/mapbox-token --profile helpmap --region us-west-2 --query SecretString --output text
```

GitHub token needs **Admin** permission on the target repo specifically
(not just token scope) for Amplify to install its webhook — a `repo`-scoped
token still 404s on `/repos/{owner}/{repo}/hooks` if the account only has
Write access. Verify directly:

```bash
curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/repos/<org>/<repo>/hooks
```
Should return `[]`, not a 404.

### Rotating the Mapbox token (`NEXT_PUBLIC_MAP_TOKEN`)

**Confirmed Aug 24:** updating the `helpmap/mapbox-token` secret's value alone
does **not** flow through to the live site — not even after `cdk deploy` +
an Amplify rebuild. Symptom: `aws secretsmanager describe-secret` keeps
showing the secret's "last retrieved" date as whenever it was last actually
deployed (e.g. "Saturday"), never moving to today no matter how many times
you rotate the value or rebuild.

Root cause: the CDK stack sets the Amplify env var
`NEXT_PUBLIC_MAP_TOKEN` to a CloudFormation dynamic reference —
`{{resolve:secretsmanager:...}}` (confirm for yourself with
`cdk synth Helpmap-testbed-Pwa --profile helpmap | grep -A2 -i mapbox`).
CloudFormation only re-resolves a dynamic reference when it actually
performs an update on that specific resource. If `cdk diff` shows no
differences (which it will — only the *secret's value* changed, not the
CDK template text that references it), CloudFormation has no reason to
touch the Amplify resource, so it never re-resolves the token and the
literal value baked in at the last real deploy just stays there
indefinitely. `cdk deploy` in this state reliably reports "no changes to
deploy" and is a no-op — **do not expect it to fix this.**

**Fix — set the value directly on the Amplify app, bypassing CDK for just
this one rotation, then force a rebuild:**

```bash
# 1. get the full current set of env vars -- update-app REPLACES all of
#    them, it does not merge, so you need every existing key/value here
aws amplify get-app --app-id <app-id> --profile helpmap --region us-west-2 \
  --query "app.environmentVariables"

# 2. re-submit the full set with NEXT_PUBLIC_MAP_TOKEN swapped in -- copy
#    the new value straight from Secrets Manager rather than retyping it
aws secretsmanager get-secret-value --secret-id helpmap/mapbox-token \
  --profile helpmap --region us-west-2 --query SecretString --output text

aws amplify update-app --app-id <app-id> --profile helpmap --region us-west-2 \
  --environment-variables NEXT_PUBLIC_MAP_TOKEN=pk_NEW_VALUE,OTHER_KEY=other_value,...

# 3. rebuild -- the new value only reaches the live site once it's
#    compiled into the bundle
aws amplify start-job --app-id <app-id> --branch-name main --job-type RELEASE --profile helpmap --region us-west-2
```

This doesn't cause drift against CDK going forward: the next time the
stack has an actual reason to update the Amplify resource, CloudFormation
will re-resolve the dynamic reference from Secrets Manager, which will
already hold this same value by then.

**Open item, not yet done:** the CDK source (`testbed_pwa_stack.py` or
equivalent) could be changed so a secret rotation alone is enough — e.g.
by having the stack read the secret via something that forces a template
diff on every synth (a version-suffixed parameter, or just accepting a
plaintext env var set through `update-app`/`.env`-style config instead of
a dynamic reference for this specific value). Worth revisiting if this
token needs to rotate more than rarely.

---

## 10. PWA (Amplify) — deploy / rebuild

```bash
cdk diff Helpmap-testbed-Pwa --profile helpmap
cdk deploy Helpmap-testbed-Pwa --profile helpmap
```

**A `cdk deploy` that only changes environment variables does NOT
automatically trigger a new build.** The live site keeps serving whatever
was last built until you force one:

```bash
aws amplify start-job --app-id <app-id> --branch-name main --job-type RELEASE --profile helpmap --region us-west-2
aws amplify list-jobs --app-id <app-id> --branch-name main --profile helpmap --region us-west-2
```

The App ID is the subdomain segment of the `AmplifyDefaultDomain` stack
output (e.g. `d3eiplrl1udggw` in `d3eiplrl1udggw.amplifyapp.com`), or:

```bash
aws amplify list-apps --profile helpmap --region us-west-2
```

The live URL needs the branch name prepended —
`https://main.<app-id>.amplifyapp.com`, not the bare default domain.

---

## 11. PWA (Amplify) — custom domain (Squarespace)

```bash
aws amplify get-domain-association --app-id <app-id> --domain-name helpmap.us --profile helpmap --region us-west-2
```

Returns two records to add in Squarespace, both `CNAME`:

- `certificateVerificationDNSRecord` — given as a full FQDN with a trailing
  dot (e.g. `_hash.helpmap.us. CNAME _hash2.acm-validations.aws.`). In
  Squarespace: Host = only the hash portion (`_hash`), **not**
  `_hash.helpmap.us` — same doubled-domain gotcha as section 6. Value =
  the target minus only the trailing dot.
- `subDomains[].dnsRecord` — given already relative (e.g.
  `testbed CNAME d26....cloudfront.net`). Host = `testbed`, Value = as
  given.

Poll status until `AVAILABLE` (cert issuance + DNS can take minutes to a
couple hours):

```bash
aws amplify get-domain-association --app-id <app-id> --domain-name helpmap.us --profile helpmap --region us-west-2 --query domainAssociation.domainStatus
```

---

## 12. Reports API — deleting reports

Everything else on this API is intentionally open (no auth at all, just
per-IP rate limits — see the main README). Delete is the one exception,
since it's destructive and irreversible: `DELETE /reports/{id}` requires a
shared-secret header, `X-Admin-Token`, matching the server's
`ADMIN_DELETE_TOKEN` env var (set in section 4 above).

```bash
curl -X DELETE https://api-testbed.helpmap.us/reports/<report-id> \
  -H "X-Admin-Token: <the value>"
```

A successful delete returns `204 No Content`; an unknown id returns `404`;
a missing/wrong token returns `401`. If `ADMIN_DELETE_TOKEN` is unset on the
server, every delete request gets `503` (fails closed, not open).

---

## 13. Troubleshooting reference

| Symptom | Cause | Fix |
|---|---|---|
| `apt install` — "Permission denied... are you root?" | missing `sudo` | prefix with `sudo` |
| `apt install python3.12-venv` — "no installation candidate" | stale/empty package index | `sudo apt update` first |
| `.venv/bin/activate: No such file or directory` | venv created before the venv package was installed (partial/broken) | `rm -rf .venv && python3 -m venv .venv`; confirm `ls .venv/bin/` shows `activate` |
| `git clone` — "Permission denied (publickey)" | no SSH key on this machine registered with GitHub | use HTTPS clone, or generate + register a deploy key |
| nginx serves a generic `404` with `nginx/1.24.0 (Ubuntu)` footer | Ubuntu's default site still enabled and/or your site's symlink missing from `sites-enabled` | check `ls /etc/nginx/sites-enabled/`; ensure your config is symlinked in AND `sudo rm sites-enabled/default` |
| `cdk deploy`/`diff` — "Unable to resolve AWS account" | expired SSO session, or missing `--profile` flag | `aws sso login --profile helpmap`; confirm `--profile helpmap` is on the command |
| SSH — "Host key verification failed" | instance was replaced (same IP, new host key) | `ssh-keygen -R <ip>`, reconnect, accept new key |
| Amplify GitHub connection — `401 Bad credentials` | wrong/mistyped token value in the secret | `curl -H "Authorization: token X" https://api.github.com/repos/<org>/<repo>` to test the token directly |
| Amplify GitHub connection — `404` on `/hooks` despite valid token | account has Write, not Admin, on the repo — webhook management needs Admin regardless of token scope | get Admin access on the repo/org |
| `<app-id>.amplifyapp.com` doesn't load | missing branch prefix | use `https://main.<app-id>.amplifyapp.com` |
| Amplify branch shows "No deploys" | creating the branch via CDK doesn't trigger an initial build; only future pushes do | `aws amplify start-job --job-type RELEASE ...` |
| Env var change deployed but site unchanged | Amplify doesn't auto-rebuild on an env var change alone | `start-job` (or "Redeploy this version" in console) after `cdk deploy` |
| Map tiles blank, pins render fine | Mapbox tile request failing — check Network tab for `api.mapbox.com` status | `403` = token valid but blocked by a URL restriction or missing scope (check the token's dashboard settings, or issue an unrestricted one); `401` = bad/invalid token |
| Lightsail instance: CPU spike, SSH slow/frozen | resource exhaustion (check Lightsail console → Metrics; `free -h`/`swapon --show` once back in) | reboot via Lightsail **console** (Stop/Start), not a hung SSH session; consider a swap file (section 8) or a bigger bundle |
| Squarespace CNAME "still pending" indefinitely | full name (including `.helpmap.us`) entered in the Host field, doubling the domain | Host field = only the portion before `.helpmap.us`; verify with `dig CNAME <name>.helpmap.us` |
| `curl` to the API "takes forever" / hangs | on the instance itself: resource exhaustion, not app/network | `curl -v --max-time 10 <url>` to see which phase stalls; if TCP connects but nothing responds after, check instance resources per row above |
| `GET /reports` missing a report you just submitted | report's `createdAt` fell outside `REPORT_WINDOW_HOURS` (default 24h), or a client sent a backdated `createdAt` | check `app/config.py` `REPORT_WINDOW_HOURS`; query the DB directly to confirm the row exists but is outside the window |
| `POST /reports` with a photo returns `422` | base64 photo exceeds `MAX_PHOTO_BASE64_CHARS` (default 8,000,000 chars ≈ 6MB) | compress client-side, or raise the limit in `app/config.py` and restart the service |
| `DELETE /reports/{id}` returns `503` | `ADMIN_DELETE_TOKEN` not set on the server (fails closed by design) | set it in `.env` per section 4, restart `helpmap-api` |
| Rotated a secret (e.g. Mapbox token), rebuilt Amplify, new value still not live; secret's "last retrieved" timestamp never updates | Amplify env var is a CFN dynamic secretsmanager reference; `cdk diff`/`deploy` show no changes (template text didn't change) so CloudFormation never re-resolves it | confirm with `cdk synth <PwaStack> \| grep -i <var-name>`; if it's `{{resolve:secretsmanager:...}}`, set the value directly via `aws amplify update-app --environment-variables ...` then `start-job` — see section 9 "Rotating the Mapbox token" |