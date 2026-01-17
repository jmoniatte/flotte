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
# Clone and install with uv
cd flotte
uv venv
uv pip install -e .
```

Or use the install script:
```bash
./install.sh
```

## Configuration

Before running, create `~/.config/flotte/config.toml` with your main repo path:

```bash
mkdir -p ~/.config/flotte
cat > ~/.config/flotte/config.toml << 'EOF'
# Path to main repo (worktrees are created as siblings)
main_repo_path = "/path/to/myproject"

poll_interval = 5
auto_discover = true
EOF
```

Edit `main_repo_path` to point to your docker-compose project. This is required - the app will create an empty config on first run, but won't work until you set this path.

## Usage

```bash
uv run flotte
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `?` | Show help |
| `s` | Start environment |
| `x` | Stop environment |
| `r` | Restart environment |
| `c` | Create worktree |
| `d` | Delete worktree |
| `l` | View logs |
| `Tab` | Focus next |
| `Esc` | Deselect |
| `q` | Quit |
