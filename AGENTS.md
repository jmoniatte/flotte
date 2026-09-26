# Flotte

TUI for managing docker-compose projects across git worktrees. The themes, the header and its
messages, Help, the confirm dialog and the startup come from
[tui-kit](https://github.com/jmoniatte/tui-kit), shared with outils and yafyaf-tui.

## Rules

- Do not git commit unless asked
- The help screen (`?`, or clicking the logo, tui-kit's `HelpScreen`) lists every binding that
  has a description and a `group` (`tui_kit.shortcuts.ACTIONS` or `GENERAL`) in
  `FlotteApp.HELP_BINDINGS` and `FlotteApp.BINDINGS`; document a new key there
- Code that every app would use goes in tui-kit, not here; see its AGENTS.md

## Run

```bash
flotte
```

It refuses to start unless stdin and stdout are a terminal (tui-kit's `start`).

## Test

Run both from the git root; the tests read style files by relative path.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. tui-kit comes from GitHub's master (`[tool.uv.sources]`); after a push there,
`uv lock --upgrade-package tui-kit` picks it up. To work on both at once, switch that source to
the commented-out `../tui-kit` path. `ruff` is pinned in the `dev` dependency group, so use
`uv run ruff`, not whatever `ruff` is on PATH.

## Structure

```
flotte/                 # git root + pyproject.toml (run uv commands here)
  flotte/               # Python package
    app.py              # Main Textual app (a tui-kit BaseApp: theme, header messages, Help)
    config.py           # Config loading (~/.config/flotte/config.yaml); the theme through tui_kit.config
    colors.py           # The Rich colors taken from tui_kit's palette, and the status icons and colors
    services/           # WorktreeManager, DockerManager, RideWrapper
    widgets/            # Textual widgets
    screens/            # Textual screens (create and delete worktree, logs)
    styles/base.tcss    # flotte's own styles, joined after tui-kit's (see app.STYLE_FILES)
```

## Themes

Themes live in tui-kit: the base16 schemes, the terminal's own palette, the picker and the rules
for all of them are in its AGENTS.md. `FlotteApp` is a `tui_kit.base_app.BaseApp`, so `t` opens
the picker and the choice is saved to the config file. There is no Settings panel: the theme
was all it held. `colors.theme_colors` turns `BaseApp.palette` into `app.theme_colors`, the
colors the tables bake into Rich text. Anything that renders a Rich colour from
`app.theme_colors` must be rebuilt in `_repaint_themed_content`, because `refresh_css` only
re-applies TCSS; `FlotteApp.apply_theme` calls it.

`base.tcss` only holds what differs from tui_kit: flotte's screens and forms. Like every app on
tui-kit, flotte draws no border around the screen; the window manager frames the window. Never
hardcode a color in it. For text on an accent background use `color: auto`, which picks a
contrasting foreground per theme.

## Config

`~/.config/flotte/config.yaml` - requires at least one project entry with `name` and `path`.

Config structure:
- `theme`: color theme, a scheme name from tui_kit or `terminal` (global); `t` writes it back
- `projects`: list of project configs (name, path, ride_command, post_create_commands)

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix (the `v0.x` tags are
from before the switch). Release by tagging the next version after the latest one:
`git describe --tags --abbrev=0`.
