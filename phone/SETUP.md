# Termux Phone Setup Guide

Complete setup from a fresh Termux install to a fully operational polymarket executor + Copilot CLI.

---

## 1. Install Termux

Install from **F-Droid** (not the Play Store — the Play Store version is outdated and no longer maintained).

- F-Droid: https://f-droid.org → search "Termux"

---

## 2. Initial package setup

```bash
pkg update -y && pkg upgrade -y
pkg install -y openssh python nodejs git
```

> **Note:** If a future `pkg upgrade` updates Python to a new minor version (e.g. 3.12 → 3.13), all pip packages will be wiped and must be reinstalled (step 5).

---

## 3. Enable SSH access

```bash
# Start the SSH daemon (port 8022)
sshd

# Set a password (needed for first key copy)
passwd
```

From your PC, copy your SSH public key:
```bash
ssh-copy-id -p 8022 <phone-ip>
```

Or manually append your public key to `~/.ssh/authorized_keys`.

To start sshd automatically on Termux launch, add it to `~/.bashrc`:
```bash
echo 'sshd' >> ~/.bashrc
```

---

## 4. Deploy polymarket scripts

The scripts live in the repo under `phone/`. Copy them to the phone:

```bash
# From your PC (repo root):
scp -P 8022 phone/polymarket_executor.py root@<phone-ip>:~/polymarket_executor.py
scp -P 8022 phone/polymarket_monitor_executor.py root@<phone-ip>:~/polymarket_monitor_executor.py
```

---

## 5. Install Python dependencies

```bash
pip install requests python-dotenv "eth-keys==0.4.0" "eth-hash[pycryptodome]" poly-eip712-structs --no-deps
# Then install poly-eip712-structs without its deps (avoids pulling eth-utils>=4 which needs Rust):
pip install poly-eip712-structs --no-deps
```

> **Why these specific versions and flags?**
> - `eth-keys==0.4.0` pulls `eth-utils==2.3.2` automatically — both pure Python, no Rust.
> - `eth-hash[pycryptodome]` provides keccak hashing without Rust.
> - `poly-eip712-structs --no-deps` avoids pulling `eth-utils>=4.1.1` which requires `pydantic-core` (Rust build, fails on Android ARM64).
> - `eth-account` and `eth-keys>=0.5` are NOT compatible with Android ARM64 due to `pydantic-core`.

---

## 6. Create `.polymarket.env`

```bash
cat > ~/.polymarket.env <<'EOF'
TELEGRAM_BOT_TOKEN=...
TELEGRAM_PERSONAL_CHAT_ID=...
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...
POLY_FUNDER=0x...
POLY_SIGNER_ADDRESS=0x...
POLY_PRIVATE_KEY=...
EOF
chmod 600 ~/.polymarket.env
```

All values come from Polymarket's API credentials page and your wallet.

---

## 7. Set up cron (executor schedule)

```bash
pkg install cronie
crond  # start the cron daemon

# Add to ~/.bashrc so it starts with every Termux session:
echo 'crond 2>/dev/null' >> ~/.bashrc
```

Edit the crontab:
```bash
crontab -e
```

Add these entries (times are Spain local — adjust if your timezone differs):

```cron
# Polymarket executor — 5 min after each server cycle (UTC+2, cycles at 00/06/12/18 UTC)
5 2 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 8 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 14 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1
5 20 * * * python ~/polymarket_executor.py >> ~/polymarket_executor.log 2>&1

# Monitor executor — 5 min after each monitor check (odd UTC hours, UTC+2)
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
5 1 * * * python ~/polymarket_monitor_executor.py >> ~/polymarket_monitor_executor.log 2>&1
```

---

## 8. Install GitHub Copilot CLI

Node.js is already installed by `pkg` (step 2). The only issue on Android ARM64 is that the bundled `pty.node` native module has no prebuild for `android-arm64` — we fix it with a symlink.

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

# 3. Install node-pty inside the Copilot module (triggers native build)
COP="$PREFIX/lib/node_modules/@github/copilot"
cd "$COP"
npm install node-pty

# 4. Create the android-arm64 symlink
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

The warning `Cannot open directory .../tls/certs` is harmless and can be ignored.

> **If Copilot breaks after a future update:** re-run steps 3 and 4 — the `npm install node-pty` + symlink is the only fragile part.

---

## 9. Authenticate Copilot with GitHub

Add your GitHub OAuth token to `.bashrc`:

```bash
echo 'export GH_TOKEN=<your-github-token>' >> ~/.bashrc
source ~/.bashrc
```

To obtain the token from the Hetzner server (where `gh auth login` was already done):
```bash
ssh root@168.119.231.76 "gh auth token"
```

Test that everything works:
```bash
copilot -p "Tell me a joke" --model gpt-4.1 -s --allow-all
```

---

## Summary checklist

- [ ] Termux installed from F-Droid
- [ ] `openssh`, `python`, `nodejs`, `git` installed
- [ ] SSH key configured (port 8022)
- [ ] `polymarket_executor.py` and `polymarket_monitor_executor.py` deployed to `~/`
- [ ] Python deps installed: `requests`, `python-dotenv`, `eth-keys<0.5`, `eth-utils<3`, `poly-eip712-structs`
- [ ] `~/.polymarket.env` created with credentials (chmod 600)
- [ ] `cronie` installed and `crond` added to `.bashrc`
- [ ] Crontab configured (executor + monitor schedules)
- [ ] Copilot CLI installed with `pty.node` symlink
- [ ] `GH_TOKEN` added to `.bashrc`
