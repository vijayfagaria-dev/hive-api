# Hive — Deploy runbook (free + always-on)

Target: **Oracle Cloud Always Free VM** (never sleeps) running both apps behind
**Caddy** (auto-HTTPS) on a **DuckDNS** subdomain. Everything here is ₹0/forever.
Channels: in-app + Web Push (free) + Gmail email (free) + WhatsApp Cloud API dev tier (free).

## Who does what
- **You (browser/accounts — I can't do these):** create the Oracle account + VM, the
  DuckDNS subdomain, the Gmail App Password, and the Meta/WhatsApp app. Bring back the
  values listed in **"Hand me back"** at the bottom.
- **Me:** generate/finalize secrets, fill the `.env` files, and give you exact copy-paste
  server commands. The artifacts in `deploy/` (Caddyfile, systemd units, env templates) are ready.

---

## Phase 1 — Oracle Cloud VM (you)
1. Sign up at cloud.oracle.com (needs a card for identity check; **Always Free never charges**).
2. **Create instance** → image **Ubuntu 22.04/24.04**. Shape:
   - Prefer **Ampere (ARM) — VM.Standard.A1.Flex**, 1–2 OCPU / 6–12 GB (Always Free, roomy).
   - If ARM capacity is unavailable, use **VM.Standard.E2.1.Micro** (AMD, 1 GB) — we'll add swap.
3. Add your SSH public key. Note the **public IP**.
4. **Open ports 80 + 443 (two places, both required on Oracle):**
   - OCI console → the VM's subnet → **Security List** → add Ingress rules: TCP 80 and 443 from `0.0.0.0/0`.
   - On the box: `sudo iptables -I INPUT 6 -p tcp -m state --state NEW -m tcp --dport 443 -j ACCEPT`
     and the same for `80`, then `sudo netfilter-persistent save` (Oracle images block by default).
5. SSH in: `ssh ubuntu@<PUBLIC_IP>`.

## Phase 2 — DuckDNS subdomain (you)
1. duckdns.org → sign in (GitHub/Google) → create e.g. `hive-flat` → it gives `hive-flat.duckdns.org` + a token.
2. Set its IP to the VM's public IP (the DuckDNS dashboard field, or `curl "https://www.duckdns.org/update?domains=hive-flat&token=<TOKEN>&ip=<PUBLIC_IP>"`).
3. (Nice-to-have) a cron on the box to keep the IP fresh.

## Phase 3 — Server bootstrap (me → you paste)
```bash
# (1 GB AMD micro) add swap first so installs/build don't OOM:
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo apt update && sudo apt install -y git software-properties-common curl

# Python 3.11+ (app uses StrEnum; Ubuntu 22.04 ships only 3.10):
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update && sudo apt install -y python3.11 python3.11-venv

# Node 20 (Next 16 needs >=18.18; the apt 'nodejs' on 22.04 is far too old):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Caddy (auto-HTTPS):
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# App user + persistent data dir (DB + proofs survive redeploys):
sudo useradd -r -m -d /opt/hive -s /bin/bash hive
sudo mkdir -p /var/lib/hive/proofs && sudo chown -R hive:hive /var/lib/hive

python3.11 --version && node --version && caddy version   # verify
```

## Phase 4 — Deploy both apps (me → you paste)
```bash
sudo -u hive -i
git clone https://github.com/vijayfagaria-dev/hive-api  /opt/hive/hive-api
git clone https://github.com/vijayfagaria-dev/hive-web  /opt/hive/hive-web

# Backend
cd /opt/hive/hive-api
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp deploy/env.api.example .env       # then fill secrets (Phase 6–8)
.venv/bin/python -m alembic upgrade head      # schema of record (not just create_all)

# Frontend
cd /opt/hive/hive-web
npm ci && npm run build
cp /opt/hive/hive-api/deploy/env.web.example .env
exit
```
Install services + Caddy:
```bash
sudo cp /opt/hive/hive-api/deploy/hive-api.service /etc/systemd/system/
sudo cp /opt/hive/hive-api/deploy/hive-web.service /etc/systemd/system/
sudo cp /opt/hive/hive-api/deploy/Caddyfile /etc/caddy/Caddyfile   # edit the host line!
sudo systemctl daemon-reload
sudo systemctl enable --now hive-api hive-web
sudo systemctl reload caddy
```
Visit `https://hive-flat.duckdns.org` — Caddy issues the TLS cert automatically.

## Phase 5 — Secrets (me; generate ON the server)
```bash
# session signing key:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"     # → SECRET_KEY

# Web Push keypair — uses the backend venv (py_vapid is already installed; no npm needed):
/opt/hive/hive-api/.venv/bin/python - <<'PY'
import base64
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization
v = Vapid01(); v.generate_keys()
b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
print("VAPID_PUBLIC_KEY=",  b64u(v.public_key.public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)))
print("VAPID_PRIVATE_KEY=", b64u(v.private_key.private_numbers().private_value.to_bytes(32, "big")))
PY
# (alternative if you prefer Node: `npx web-push generate-vapid-keys`)
```
Put them in `/opt/hive/hive-api/.env`, set `VAPID_SUBJECT=mailto:<you>`, `COOKIE_SECURE=true`,
`APP_BASE_URL=https://hive-flat.duckdns.org`, then `sudo systemctl restart hive-api`.

## Phase 6 — Gmail email (you)
1. On the Google account: enable **2-Step Verification**.
2. Google Account → Security → **App passwords** → generate one (“Mail”) → 16 chars.
3. Put it in `.env`: `SMTP_USERNAME=<gmail>`, `SMTP_PASSWORD=<app password>`, `SMTP_FROM=Hive 🐝 <gmail>`.

## Phase 7 — WhatsApp Cloud API, dev tier (you)
1. developers.facebook.com → **Create App** → type **Business** → add the **WhatsApp** product.
2. WhatsApp → **API Setup**: note the **Phone number ID** (test number is provided free).
   Add each flatmate's number as a **recipient** (each confirms an OTP). Dev tier allows ≤5.
3. **Permanent token:** business.facebook.com → Business settings → **System users** → add one →
   assign the WhatsApp app/asset → **Generate token** with `whatsapp_business_messaging`
   (and `whatsapp_business_management`). → `WHATSAPP_TOKEN`.
4. **Message template:** WhatsApp Manager → Templates → **Create** → name `hive_alert`,
   category **Utility**, language **English**, **Body** exactly: `Hive 🐝 {{1}}` → submit (approves in minutes).
5. Fill `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` in `.env`, restart hive-api. Flatmates add
   their number in the app (Settings → WhatsApp).

## Phase 8 — Go-live checks
```bash
curl -s https://hive-flat.duckdns.org/api/public/stats     # should return JSON
curl -s https://hive-flat.duckdns.org/health               # internal; via Caddy may 404 (fine)
# Promote yourself to tenant after you register in the web app:
sudo -u hive /opt/hive/hive-api/.venv/bin/python -m app.admin promote <your-username>
```

## Phase 9 — Backups (free)
A nightly copy of the DB + proofs (cron as the `hive` user):
```bash
0 3 * * *  sqlite3 /var/lib/hive/hive.db ".backup '/var/lib/hive/backup-$(date +\%F).db'" && \
           tar czf /var/lib/hive/proofs-$(date +\%F).tgz -C /var/lib/hive proofs && \
           find /var/lib/hive -name 'backup-*.db' -mtime +7 -delete
```

## Redeploys
```bash
cd /opt/hive/hive-api && git pull && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m alembic upgrade head && sudo systemctl restart hive-api
cd /opt/hive/hive-web && git pull && npm ci && npm run build && sudo systemctl restart hive-web
```

## Gotchas (don't get bitten)
- **Single API worker** (`--workers 1`) — or the sweep double-fires notifications.
- **Ports 80/443** must be open in **both** the OCI Security List **and** iptables.
- **`alembic upgrade head` on every deploy** — `create_all` only adds missing *tables*, not new *columns*.
- **`COOKIE_SECURE=true`** only works over HTTPS (Caddy gives you that).
- DB + proofs live in **`/var/lib/hive`** (persistent), not inside the repo.

---

## Hand me back (so I finalize the configs)
1. The VM **public IP** + that SSH works.
2. The **DuckDNS subdomain** (+ token if you want the auto-IP cron).
3. Gmail **App Password** + the sending address.
4. WhatsApp **Phone Number ID** + the **permanent token** + confirmation the `hive_alert` template is approved.
> Don't paste secrets into a shared channel if you can avoid it — better to generate `SECRET_KEY`/VAPID
> on the box (Phase 5) and only fill `.env` there. For Gmail/WhatsApp tokens, set them directly in the
> server `.env`; tell me when they're in and I'll verify the wiring.
