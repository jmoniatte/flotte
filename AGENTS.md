# Flotte

TUI for managing docker-compose projects across git worktrees.

## Rules

- Do not git commit unless asked
- The settings screen lists every binding that has a description and a `group`
  (`shortcuts.ACTIONS` or `shortcuts.GENERAL`); document a new key there, not in
  `settings_screen.py`

## Run

```bash
flotte
```

## Test

Run both from the git root; the tests read style files by relative path.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. `ruff` is pinned in the `dev` dependency group, so use
`uv run ruff`, not whatever `ruff` is on PATH.

## Structure

```
flotte/                 # git root + pyproject.toml (run uv commands here)
  flotte/               # Python package
    app.py              # Main Textual app
    config.py           # Config loading (~/.config/flotte/config.yaml)
    shortcuts.py        # Settings screen shortcuts, read off the bindings
    services/           # WorktreeManager, DockerManager, RideWrapper
    widgets/            # Textual widgets
    screens/            # Textual screens
    theme.py            # base16 scheme loading, palette derivation
    styles/themes/      # base16 scheme files, one .yaml per theme
```

## Themes

`flotte/styles/themes/` holds the whole
[base16 catalogue](https://github.com/tinted-theming/schemes), one scheme file
per theme, copied in unmodified - never hand-edit one. `theme.py` maps 11 of
the 16 slots straight onto the TCSS variables `base.tcss` uses and derives the
other two (`$bg-dark`, `$gutter`) from the scheme's greyscale ramp, so adding a
theme means adding a file and nothing else. `config.py` rejects a `theme` that
does not name one of them.

Filenames are the upstream scheme slugs verbatim, and that is exactly what
`config.yaml` sets -- no aliases, no renaming. Upstream is inconsistent about
hyphens (`onedark` but `one-light`); follow it rather than tidying it.

`scripts/sync_themes.py` refreshes the directory from upstream. It is the only
place the editorial rule lives: a scheme whose own `$fg` on `$bg` falls below
`MIN_TEXT_CONTRAST` (WCAG AA) is skipped, since `base.tcss` cannot rescue it.
Do not hand-add a scheme the script would reject.

Settings (`?`) has a theme dropdown; the picker (`t`) previews as the cursor
moves. Both route through `FlotteApp.set_theme`. The palette is
served from `FlotteApp.get_css_variables` rather than baked into `CSS`. Anything
that renders a Rich colour from `app.theme_colors` must be rebuilt in
`_repaint_themed_content`, because `refresh_css` only re-applies TCSS.

Never hardcode a color in `base.tcss`. For text on an accent background use
`color: auto`, which picks a contrasting foreground per theme.

## Config

`~/.config/flotte/config.yaml` - requires at least one project entry with `name` and `path`.

Config structure:
- `theme`: color theme, matching a file in `flotte/styles/themes/` (global)
- `projects`: list of project configs (name, path, ride_command, post_create_commands)
