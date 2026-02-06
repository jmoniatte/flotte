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
flotte/                 # git root + pyproject.toml (run uv commands here)
  flotte/               # Python package
    app.py              # Main Textual app
    config.py           # Config loading (~/.config/flotte/config.yaml)
    services/           # WorktreeManager, DockerManager, RideWrapper
    widgets/            # Textual widgets
    screens/            # Textual screens
```

## Config

`~/.config/flotte/config.yaml` - requires at least one project entry with `name` and `path`.

Config structure:
- `theme`: color theme - onedark or onelight (global)
- `projects`: list of project configs (name, path, ride_command)
