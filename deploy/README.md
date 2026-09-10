# Deploying

There is no deploy script. The host has a checkout with an `origin` pointing
at GitHub, and `setup.sh` runs there — so a deploy is a pull and one command,
and the thing that runs as root is a script you have already read.

```bash
ssh <host>
cd ~/display-mcp
git pull --ff-only
sudo ./deploy/setup.sh sync     # code change: reinstall into the venv, restart
```

`sync` is the everyday one. Reach for `install` when something structural
changed — a dependency in `pyproject.toml`, the unit, the bind address, the
Access settings, or when adding the tunnel:

```bash
sudo ./deploy/setup.sh install                 # idempotent; safe to re-run
sudo ./deploy/setup.sh install --dry-run       # prints the plan, changes nothing
./deploy/setup.sh status                       # no root needed
```

`setup.sh --help` documents every command and flag. It is idempotent and
reversible: `uninstall` puts the machine back, `--purge` also takes the state
directory and the service user.

**The host pulls from GitHub, so push first.** A commit sitting on your laptop
is one the host cannot see, and the failure looks like a deploy that ran
cleanly and changed nothing.

## Configuring the edge

These go on `install`, and they are the only reason to pass flags in normal
use:

```bash
# bring the tunnel up. No --tunnel-token: setup.sh prompts with echo off, so
# the token stays out of your shell history and the host's process list.
sudo ./deploy/setup.sh install --with-tunnel

# verify the Cloudflare Access JWT on every MCP request
sudo ./deploy/setup.sh install \
  --access-team-domain https://<team>.cloudflareaccess.com \
  --access-aud <aud tag>

# record the tunnel's public hostname so status can print it back
sudo ./deploy/setup.sh install --domain mcp.example.com
```

Pass no Access flags and the MCP endpoint verifies nothing — `status` says so
under `mcp auth`. That is fine while it is loopback-only, and not fine once
the tunnel is up.

## First time on the host

```bash
git clone https://github.com/<owner>/display-mcp.git ~/display-mcp
cd ~/display-mcp
sudo ./deploy/setup.sh install --dry-run    # read the plan first
sudo ./deploy/setup.sh install
```

`setup.sh` installs the application into `/opt/display-mcp`, owned by the
`display-mcp` system user. The checkout in your home directory is the source
of truth; `/opt/display-mcp` is what the service runs — specifically
`/opt/display-mcp/app`, a copy of `pyproject.toml`, `README.md`, `src/`,
`samples/` and `docs/SPEC.md`, pip-installed non-editable into
`/opt/display-mcp/venv`.

Keeping the checkout and the install separate is what makes a half-finished
pull harmless: nothing the service runs changes until `sync` says so.
`docs/RUNBOOK.md` walks the same sequence with a gate on each step, which is
where to look when one of them fails.
