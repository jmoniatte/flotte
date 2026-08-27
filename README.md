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
  - name: Acme API
    repository_path: /var/www/acme-api
    worktree_path: /var/www/worktrees/{worktree}/acme-api
```

Each project requires:

- `name`: Display name shown in the sidebar.
- `repository_path`: Path to the main Git checkout.
- `worktree_path`: Destination template containing `{worktree}`.

Optional fields:

- `post_create_commands`: Setup commands run after creating a worktree.
- `ride_command`: Command used by **Go Ride**. It receives `PROJECT_PATH` and `PROJECT_NAME`.
- `env_file`: Worktree environment file read and written by Flotte. Defaults to `.env`.
- `clone_paths`: Files or directories copied from the main checkout when cloning volumes and bind
  mounts.
- `linked_repositories`: Companion repositories paired with the project.

The global `theme` can be `onedark` (default) or `onelight`.

## Linked repositories

Use a linked repository when part of a project, such as a React frontend, lives in a separate Git
repository but should follow the primary project's branch and worktree.

This complete config pairs a Docker-backed API with a React app served by Vite:

```yaml
theme: onedark

projects:
  - name: Acme API
    repository_path: /var/www/acme-api
    worktree_path: /var/www/worktrees/{worktree}/acme-api
    linked_repositories:
      - repository_path: /var/www/acme-web
        worktree_path: /var/www/worktrees/{worktree}/acme-web
        ports:
          vite: "5100-5199"
        post_create_commands:
          - pnpm install
        pre_start_commands:
          - printf 'VITE_PORT=%s\n' "$FLOTTE_PORT_VITE" > .env.local
        start_command: pnpm dev -- --port "$FLOTTE_PORT_VITE"
        status_port_env: VITE_PORT
        status_port_file: .env.local
        status_port_label: Vite
```

Select a primary worktree and choose **Link**. Flotte creates the linked worktree on the same
branch, assigns its Vite port, installs dependencies, and starts the dev server. **Start**,
**Stop**, and **Restart** then manage that server. The start command must stay in the foreground
so Flotte can track it.

Choose **Unlink** to remove the paired worktree and release its ports. Flotte refuses to unlink a
repository with uncommitted changes.

### Linked repository options

| Field | Purpose |
| --- | --- |
| `repository_path` | Main checkout of the linked repository. Required. |
| `worktree_path` | Linked worktree template containing `{worktree}`. Required. |
| `ports` | Named inclusive port ranges. A `vite` port is exposed as `FLOTTE_PORT_VITE`. |
| `post_create_commands` | Run once after creating the linked worktree. |
| `pre_start_commands` | Run before every process start. |
| `start_command` | Foreground process managed by Flotte. |
| `post_delete_commands` | Run before removing the linked worktree. |
| `status_port_env` | Variable read from `status_port_file` to display the process port. |
| `status_port_file` | File containing `status_port_env`. Defaults to `.env.local`. |
| `status_port_label` | Label shown beside the port. Defaults to `Port`. |
| `open_url_path` | Path appended to the primary URL; `{port}` expands to the displayed port. |

Port assignments persist in `~/.local/state/flotte/linked-worktrees.yaml`. Linked commands receive:

- `FLOTTE_PRIMARY_PATH`: Primary worktree path.
- `FLOTTE_LINKED_PATH`: Linked worktree path.
- `FLOTTE_WORKTREE_NAME`: Worktree name.
- `FLOTTE_BRANCH`: Branch name.
- `FLOTTE_PORT_<NAME>`: Assigned port for each entry in `ports`.

### Post-create commands

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
