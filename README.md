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

Create `~/.config/flotte/config.toml`:

```toml
theme = "onedark"

[[projects]]
name = "My Project"
path = "/var/www/my-project"
worktree_path = "/var/www/"
worktree_prefix = "my-project"
ride_command = ""
```

**Required fields:**
- `name` - Project display name
- `path` - Path to main git repo
- `worktree_path` - Directory where new worktrees are created
- `worktree_prefix` - Prefix for worktree directory names (use `""` for no prefix)

**Optional fields:**
- `theme` - Color theme: `onedark` (default) or `onelight`
- `ride_command` - Command for "Go Ride" button (receives `PROJECT_PATH` and `PROJECT_NAME` env vars)

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
