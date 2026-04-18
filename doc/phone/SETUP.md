# Termux Phone Setup Guide

Complete setup from a fresh Termux install to a fully operational phone:
- Polymarket order executor (signs + submits orders via residential IP)
- Beecthor video summarizer (transcript → Copilot → Telegram + repo)
- GitHub Copilot CLI

---

## 1. Install Termux

Install from **F-Droid** (not the Play Store — the Play Store version is outdated and no longer maintained).

- F-Droid: https://f-droid.org → search "Termux"

---

## 2. Initial package setup

```bash
pkg update -y && pkg upgrade -y
pkg install -y openssh python nodejs git cronie
```

> **Note:** If a future `pkg upgrade` updates Python to a new minor version (e.g. 3.12 → 3.13), all pip packages will be wiped and must be reinstalled (step 5).

---

## 3. Enable SSH + cron on startup

Add both daemons to `~/.bashrc` so they start every time Termux opens:

```bash
echo 'sshd' >> ~/.bashrc
echo 'crond 2>/dev/null' >> ~/.bashrc
source ~/.bashrc
```

For the first SSH connection, set a password and copy your public key:
```bash
passwd
```
From your PC:
```bash
ssh-copy-id -p 8022 <phone-ip>
```

### How to discover the SSH connection details

On the phone (inside Termux):

```bash
# SSH username
whoami

# Confirm Termux SSH is running
sshd

# Confirm the device IP on your local network
ip addr show wlan0
```

On your PC (PowerShell):

```powershell
# List your local public SSH keys
Get-ChildItem -Force $HOME\.ssh -Filter *.pub

# Read the public key you want to install on the phone or server
Get-Content $HOME\.ssh\id_ed25519.pub

# Optional: test whether the phone SSH port is reachable
Test-NetConnection <phone-ip> -Port 8022

# Optional: test whether a server SSH port is reachable
Test-NetConnection <server-ip> -Port 22
```

Keep the discovered values private. Do not commit IPs, usernames, private keys, or live credentials into the repository.

---

## 4. Clone the repo

```bash
git clone https://github.com/jmtdev0/beecthor-summary.git ~/beecthor-summary
```

Then deploy the phone scripts:
```bash
cp ~/beecthor-summary/phone/polymarket_executor.py ~/polymarket_executor.py
cp ~/beecthor-summary/phone/polymarket_monitor_executor.py ~/polymarket_monitor_executor.py
cp ~/beecthor-summary/phone/beecthor_summarizer.py ~/beecthor_summarizer.py
```

---

## 5. Install Python dependencies

```bash
# Core deps (requests, dotenv)
pip install requests python-dotenv defusedxml

# EIP-712 signing stack — no Rust required on ARM64
pip install "eth-keys==0.4.0" "eth-hash[pycryptodome]"
pip install poly-eip712-structs --no-deps

# YouTube transcript (for Beecthor summarizer)
pip install youtube-transcript-api --no-deps
```

> **Why these specific versions and flags?**
> - `eth-keys==0.4.0` pulls `eth-utils==2.3.2` automatically — both pure Python, no Rust.
> - `eth-hash[pycryptodome]` provides keccak hashing without Rust.
> - `poly-eip712-structs --no-deps` avoids pulling `eth-utils>=4.1.1` which requires `pydantic-core` (Rust build, fails on Android ARM64).
> - `youtube-transcript-api --no-deps` avoids version conflicts; `defusedxml` and `requests` are already installed.
> - `eth-account` and `eth-keys>=0.5` are NOT compatible with Android ARM64 due to `pydantic-core`.

---

## 6. Create `~/.polymarket.env`

```bash
cat > ~/.polymarket.env <<'EOF'
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_PERSONAL_CHAT_ID=...
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...
POLY_FUNDER=0x...
POLY_SIGNER_ADDRESS=0x...
POLY_PRIVATE_KEY=...
GH_TOKEN=...
SERVER_LOG_API_URL=https://<server-host>/api/mobile-log
SERVER_LOG_API_SECRET=...
EOF
chmod 600 ~/.polymarket.env
```

- `TELEGRAM_CHAT_ID` — the group chat (used by Beecthor summarizer)
- `TELEGRAM_PERSONAL_CHAT_ID` — your personal chat (used by executors)
- `GH_TOKEN` — GitHub OAuth token (used by summarizer to push to repo)
- `SERVER_LOG_API_URL` — private dashboard ingestion endpoint for structured phone logs
- `SERVER_LOG_API_SECRET` — shared secret accepted by `/api/mobile-log`

To get the GitHub token from the Hetzner server:
```bash
ssh root@168.119.231.76 "gh auth token"
```

---

## 7. Add `GH_TOKEN` to `.bashrc` (for Copilot CLI)

```bash
echo 'export GH_TOKEN=<your-github-token>' >> ~/.bashrc
source ~/.bashrc
```

> The token serves double duty: Copilot CLI authentication + git push in the summarizer.

---

## 8. Set up crontab

```bash
crontab -e
```

Add:

```cron
CRON_TZ=UTC

# Polymarket executor — 5 min after each server cycle (cycles at 00/06/12/18 UTC)
5 0 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 6 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 12 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 18 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1

# Monitor executor — 5 min after each monitor check (odd UTC hours)
5 1 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 3 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 5 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 7 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 9 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 11 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 13 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 15 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 17 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 19 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 21 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
5 23 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1

# Beecthor summarizer — daily at 19:45 UTC
45 19 * * * source $HOME/.bashrc && python $HOME/beecthor_summarizer.py >> $HOME/beecthor_summarizer.log 2>&1
```

> The executor reads from `pending_orders.json` in the repo and executes all queued orders. It deduplicates by order ID so running it multiple times is safe.

---

## 9. Install GitHub Copilot CLI

Node.js is already installed (step 2). The only issue on Android ARM64 is that the bundled `pty.node` native module has no prebuild — we fix it with a symlink after a native build.

```bash
# 1. GYP override (avoids android_ndk_path errors during native builds)
mkdir -p ~/.gyp
cat > ~/.gyp/include.gypi <<'GYP'
{
  "variables": {
    "android_ndk_path": ""
  }
}
GYP

# 2. Install Copilot CLI
npm install -g @github/copilot

# 3. Build node-pty from source inside the Copilot module
COP="$PREFIX/lib/node_modules/@github/copilot"
cd "$COP"
npm install node-pty

# 4. Symlink the built binary to where Copilot looks for it
PTY_SRC="$COP/node_modules/node-pty/build/Release/pty.node"
PTY_DST_DIR="$COP/prebuilds/android-arm64"
mkdir -p "$PTY_DST_DIR"
ln -sf "$PTY_SRC" "$PTY_DST_DIR/pty.node"

# 5. Verify
copilot --version
```

Expected output:
```
GitHub Copilot CLI 1.0.12.
Run 'copilot update' to check for updates.
```

The warning `Cannot open directory .../tls/certs` is harmless.

> **If Copilot breaks after a future `npm` update:** re-run steps 3 and 4 only.
> **If that still fails:** use proot-distro Ubuntu as fallback:
> ```bash
> proot-distro install ubuntu
> # install node + copilot inside Ubuntu, then call via wrapper script
> ```

---

## 10. Test everything

```bash
# Copilot
copilot -p "Tell me a joke" --model gpt-4.1 -s --allow-all

# Executor (reads pending_orders.json from repo — safe to run even if empty)
python ~/polymarket_executor.py

# Beecthor summarizer (will skip if today's video was already processed)
python ~/beecthor_summarizer.py
```

---

## Summary checklist

- [ ] Termux installed from F-Droid
- [ ] `openssh`, `python`, `nodejs`, `git`, `cronie` installed
- [ ] `sshd` and `crond` added to `~/.bashrc`
- [ ] SSH key configured (port 8022)
- [ ] Repo cloned to `~/beecthor-summary`
- [ ] Phone scripts deployed to `~/`
- [ ] Python deps installed (see step 5)
- [ ] `~/.polymarket.env` created with all credentials (chmod 600)
- [ ] `GH_TOKEN` exported in `~/.bashrc`
- [ ] Crontab configured (executor + monitor + summarizer)
- [ ] Copilot CLI installed with `pty.node` symlink
- [ ] All three scripts tested manually
