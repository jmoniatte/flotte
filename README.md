# Flotte

Terminal-based interface for managing docker-compose projects across git worktrees.

## How It Works

Given a main repo directory (e.g., `myproject/`), Flotte:
- Creates worktrees as sibling directories: `myproject-feature/`, `myproject-bugfix/`
- Each worktree gets isolated Docker volumes and offset ports
- Volumes can be cloned from main to avoid re-seeding databases

```
/path/to/
  myproject/              # main repo (port 3000)
  myproject-feature-x/    # worktree (port 3100)
  myproject-bugfix-y/     # worktree (port 3200)
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
poll_interval = 5
auto_discover = true
theme = "onedark"

[[projects]]
name = "my-project"
path = "/path/to/my-project"
ride_command = ""
```

Global settings:
- `poll_interval`: Seconds between container status polls
- `auto_discover`: Discover worktrees on startup
- `theme`: Color theme (`onedark` or `onelight`)

Each `[[projects]]` entry defines a project:
- `name`: Display name in dropdown
- `path`: Path to main git repo (worktrees created as siblings)
- `ride_command`: Optional command for "Go Ride" button (receives `PROJECT_PATH` and `PROJECT_NAME` env vars)

The first project loads automatically on startup. Use the dropdown to switch between projects.

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
