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
| `n` | New worktree |
| `d` | Delete worktree |
| `s` | Start services |
| `x` | Stop services |
| `r` | Refresh status |
| `R` | Go Ride |
| `q` | Quit |
| `?` | Show help |
