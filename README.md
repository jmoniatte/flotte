# Flotte

Terminal-based interface for managing docker-compose projects across git worktrees.

## How It Works

Flotte manages git worktrees with isolated Docker environments:
- Creates worktrees in a configurable directory with a configurable prefix
- Each worktree gets isolated Docker volumes and offset ports
- Volumes can be cloned from main to avoid re-seeding databases

```
/path/to/
  myproject/              # main repo (port 3000)
  myproject_worktrees/
    feature-x/            # worktree (port 3100)
    bugfix-y/             # worktree (port 3200)
```

## Prerequisites

The main repo must have:

1. **A `docker-compose.yml`** with named volumes (volumes are read dynamically)

2. **A `.env` file** with base port configuration:
   ```bash
   COMPOSE_PROJECT_NAME=myproject
   NGINX_PORT=3000
   RAILS_PORT=3001
   MYSQL_PORT=3306
   # ... other ports
   ```

The `COMPOSE_PROJECT_NAME` determines Docker volume naming and is used when cloning data to new worktrees.

If your project keeps this configuration somewhere other than `.env`, set `env_file` on the
project (see `config.yaml.example`). Flotte both reads and writes that file, so it must be the
same file your containers are actually started with — docker compose only auto-loads `.env`,
so any other value has to be passed with `--env-file` by whatever launches your stack.

## Installation

```bash
git clone <repo-url>
cd flotte
```

Then either:

```bash
uv tool install ./flotte
```

Or:

```bash
./install.sh
```

## Configuration

Create `~/.config/flotte/config.yaml`:

```yaml
theme: onedark

projects:
  - name: My Project
    path: /var/www/my-project
    worktree_path: /var/www/
    worktree_prefix: "my-project"
    post_create_commands:
      - mise trust
      - bundle install
    ride_command: ""
```

**Required fields:**
- `name` - Project display name
- `path` - Path to main git repo
- `worktree_path` - Directory where new worktrees are created
- `worktree_prefix` - Prefix for worktree directory names (use `""` for no prefix)

**Optional fields:**
- `theme` - Color theme: `onedark` (default) or `onelight`
- `post_create_commands` - Setup commands run once, in order, after a new worktree is created
- `ride_command` - Command for "Go Ride" button (receives `PROJECT_PATH` and `PROJECT_NAME` env vars)
- `env_file` - Env file flotte reads and writes per worktree (default: `.env`). Docker compose only
  auto-loads `.env`; anything else must be passed to compose with `--env-file` by your own tooling
- `clone_paths` - Extra files or directories, relative to the repo root, copied from the main repo
  into a new worktree. Only applied when "Clone volumes and bind mounts from main" is checked;
  paths that don't exist in the main repo are skipped
- `linked_repositories` - Optional repositories whose worktrees can be created on demand from a
  primary worktree. Each entry needs `name`, `path`, `worktree_path`, and `worktree_prefix`.

### Linked Repositories

Linked Repositories are useful for a React frontend, or any repository that should share a branch
and lifecycle with the Docker project without itself running in Docker. Select a worktree and use
the **Link** button to create its companion worktree with the same branch name. Flotte records the
pairing in local state; **Unlink** removes the companion worktree. A linked worktree is also
removed when its primary worktree is deleted. Linked worktrees must be clean before deletion.

```yaml
    linked_repositories:
      - name: Frontend
        path: /var/www/my-project-frontend
        worktree_path: /var/www/
        worktree_prefix: "my-project-frontend-"
        ports:
          dev_server: "5100-5199"
        # Read the assigned frontend port after the setup command writes this file.
        status_port_env: VITE_PORT
        status_port_file: .env.local
        status_port_label: Vite
        # Open this route in the selected Docker worktree while the frontend is running.
        open_url_path: /?hot=v:{port}
        post_create_commands:
          - /var/www/scripts/configure-project-link
        # Run before every Start, including a managed primary checkout.
        pre_start_commands:
          - /var/www/scripts/configure-project-link
        # Keep the server in the foreground so Flotte can stop and restart it.
        start_command: pnpm dev
        post_delete_commands:
          - /var/www/scripts/remove-project-link
```

`ports` maps a name to an inclusive local port range. Flotte chooses an available port and retains
the assignment in `~/.local/state/flotte/linked-worktrees.yaml`. Link commands run from the linked
worktree and receive `FLOTTE_PRIMARY_PATH`, `FLOTTE_LINKED_PATH`, `FLOTTE_WORKTREE_NAME`,
`FLOTTE_BRANCH`, and one `FLOTTE_PORT_<NAME>` variable per allocated port. The same variables are
available to `post_delete_commands`, which can remove or reset primary-repository configuration
such as a frontend URL. Commands should be idempotent so a failed setup can safely be retried.
Set `start_command` to launch a linked repository's long-running development process after setup.
Flotte records and stops that process when the linked worktree is removed. It shows **Start** when
the process is stopped, and **Stop** and **Restart** while it is running. The linked URL is shown
only while that process is running. The command must keep its server in the foreground; commands
that daemonize or background their server are externally managed and cannot be safely stopped or
restarted by Flotte.

Set `pre_start_commands` for idempotent commands that must run immediately before every managed
process start. This is useful for a primary checkout, which has no linked-worktree creation hook.

Set `status_port_env` to display a port read from the linked worktree's env file. Use
`status_port_file` to select that file (default: `.env.local`) and `status_port_label` to name the
port in the UI. This is useful when a setup hook writes the frontend's local env file. Set
`open_url_path` to the path and optional query string to open in the selected Docker worktree. Use
`{port}` to substitute the configured status port. For example, `/?hot=v:{port}` produces
`http://localhost:PORT?hot=v:27882` when the frontend's status port is `27882`.

### post_create_commands

Each entry runs through `sh -c` with the new worktree as working directory, so `&&`, pipes, globs
and `$VARS` work. They run last, once the worktree, its volumes and its copied files are all in
place, and receive three env vars:

- `PROJECT_PATH` - the new worktree's directory (same as the working directory)
- `PROJECT_NAME` - the new worktree's name, as shown in the UI
- `MAIN_REPO_PATH` - the main repo, for pulling in files git doesn't carry over:

```yaml
    post_create_commands:
      - cp "$MAIN_REPO_PATH/dev/bruno/.env" dev/bruno/.env
```

A failing command shows a warning and the remaining commands still run. Each command is given 5
minutes before it is killed. A single command can be written as a plain string instead of a list:

```yaml
    post_create_commands: mise trust
```

## Usage

```bash
flotte
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Open selected worktree |
| `b` or `Esc` | Return to worktrees (`Esc` quits from the worktree list) |
| `n` | New worktree |
| `d` | Delete worktree |
| `s` | Start services |
| `x` | Stop services |
| `r` | Refresh status |
| `R` | Go Ride |
| `q` | Quit |
| `?` | Show help |
