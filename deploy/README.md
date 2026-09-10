# Deploying

`../deploy.sh` is the path: the host pulls `main` from GitHub into its own
checkout, then runs `setup.sh` there over `ssh -t`, which prompts for your
sudo password. It never pushes, so commit and push before you run it.

```bash
export DISPLAY_MCP_HOST=user@host       # the machine running the service

./deploy.sh                 # code change: pull, sync into the venv, restart
./deploy.sh --install       # unit, drop-in, dependency, tunnel or Access change
./deploy.sh status          # what is running, what is published, is the tunnel up
```

Anything after the command goes through to `setup.sh` on the host, which is
how the edge gets configured. `./deploy.sh --help` lists these; `setup.sh
--help` on the host has the rest.

```bash
# bring the tunnel up. No --tunnel-token: setup.sh prompts with echo off, so
# the token stays out of your shell history and the host's process list.
./deploy.sh --install --with-tunnel

# verify the Access JWT on every MCP request
./deploy.sh --install \
  --access-team-domain https://<team>.cloudflareaccess.com \
  --access-aud <aud tag>

# record the tunnel's public hostname so status can print it back
./deploy.sh --install --domain mcp.example.com
```

Pass no Access flags and the MCP endpoint verifies nothing — `status` says so
under `mcp auth`. That is fine while it is loopback-only, and not fine once
the tunnel is up.

## First time on the host

The host keeps a plain checkout in the login user's home directory with an
`origin` remote pointing at GitHub. `DISPLAY_MCP_DIR` overrides the path,
which is otherwise taken relative to that home directory.

```bash
ssh "$DISPLAY_MCP_HOST" 'git clone https://github.com/<owner>/display-mcp.git ~/display-mcp'
./deploy.sh --install
```

`setup.sh` installs the application into `/opt/display-mcp`, owned by the
`display-mcp` system user. The checkout in the home directory is the source
of truth; `/opt/display-mcp` is what the service runs — specifically
`/opt/display-mcp/app`, a copy of `pyproject.toml`, `README.md`, `src/`,
`samples/` and `docs/SPEC.md`, pip-installed non-editable into
`/opt/display-mcp/venv`. Keeping the checkout and the install separate means
a half-finished pull can never take the service down.

## The push-hook alternative, and why it isn't the default

A bare repo on the host with a `post-receive` hook gives you `git push host main`
and nothing else to remember. The cost is that the hook needs to restart a
system service, so the pushing user needs a sudoers entry:

```
display-mcp ALL=(root) NOPASSWD: /usr/bin/systemctl restart display-mcp
```

That is a small, narrow grant and it is defensible. But it adds a second copy
of the repo, a shell for a `--system` user, and a root-adjacent path that runs
on every push — and it puts the deploy on a path that bypasses GitHub, so what
runs on the host need never have been reviewed there. Not worth it for one
service on a home network.
