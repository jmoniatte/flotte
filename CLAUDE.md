# Flotte

TUI for managing docker-compose projects across git worktrees.

## Rules

- Do not git commit unless asked

## Run

```bash
flotte
```

## Structure

```
flotte/                 # project dir (run uv commands here)
  flotte/               # Python package
    app.py              # Main Textual app
    config.py           # Config loading (~/.config/flotte/config.toml)
    services/           # WorktreeManager, DockerManager, RideWrapper
    widgets/            # Textual widgets
    screens/            # Textual screens
  pyproject.toml
```

## Config

`~/.config/flotte/config.toml` - requires at least one `[[projects]]` entry with `name` and `path`.

Config structure:
- `poll_interval`: seconds between status polls (global)
- `auto_discover`: discover worktrees on startup (global)
- `[[projects]]`: array of project configs (name, path, ride_command)
