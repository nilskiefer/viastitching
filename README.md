# ViaStitching 2.0

ViaStitching 2.0 is a maintained fork of the original [weirdgyn/viastitching](https://github.com/weirdgyn/viastitching), focused on modern KiCad workflows and safer editing behavior.

The plugin fills selected copper zones with stitching vias for thermal and current handling, while preserving ownership and settings per zone.

## What changed in this fork

Compared to upstream, this fork adds substantial functionality and hardening:

- KiCad 9 compatibility improvements and safer Undo/Redo behavior.
- PCB-embedded metadata for per-zone settings and owned-via tracking (versioned with the `.kicad_pcb` file).
- Dedicated actions:
  - `Update Via Array`
  - `Update Via Array (Maximize)`
  - `Remove Via Array`
  - `Clean Orphan Vias`
- Improved placement modes:
  - Standard grid placement
  - `45-degree offset` pattern
  - `Spiral` pattern
  - Target-via-count mode
  - Dense maximize packing mode (non-grid)
- Better placement quality controls:
  - Segment centering for cleaner local distribution
  - Edge and pad margins
  - Optional all-layer overlap checks
  - Optional footprint-zone blocking and same-net-under-pad behavior controls
- Stronger UX and diagnostics:
  - Better failure messages and bootstrap/load error logging
  - Preview support in dialog flow
  - Persistent prompt choices with reset support

## Requirements

- KiCad with Python plugin support (tested primarily on KiCad 9)
- No manual `pip` installation is required for normal plugin use

## Installation

Install like any other KiCad plugin by placing this folder in a KiCad plugin search path (user plugin directory recommended), then restart KiCad.

In typical usage, just install the plugin and run it from KiCad. You do not need to manually enable extra API switches or install `requirements.txt` yourself.

## Typical workflow

1. Select a copper zone in PCB Editor.
2. Run `Update Via Array` (or `Update Via Array (Maximize)`).
3. Configure via geometry and placement settings.
4. Press `OK` to apply changes.

Related maintenance actions:

- `Remove Via Array`: removes plugin-owned vias for the selected zone (optionally includes matching user vias).
- `Clean Orphan Vias`: removes plugin-owned vias no longer valid for their zone ownership.

## Behavior details

- Zone net is derived from the selected zone.
- In maximize mode, spacing/offset controls are ignored in favor of dense candidate packing.
- If zone copper is stale/unfilled, the plugin can prompt to rebuild copper.
- Ownership and zone settings are stored in PCB metadata, so git revert/checkouts keep via-array state aligned with board history.

## Troubleshooting logs

When startup or runtime fails, inspect:

- `viastitching_plugin_error.log` (plugin folder)
- `viastitching_bootstrap.log` (inside plugin files)
- `viastitching_ipc.log` in the KiCad plugin settings path for this plugin (fallback: `~/.config/viastitching/`)
- `viastitching_debug.log` (plugin folder)

## Screenshots

- Preview: `preview.png`
- Dialog: `pictures/viastitching_dialog.png`
- Result example: `pictures/viastitching_result.png`

## Attribution

- Original project: [weirdgyn/viastitching](https://github.com/weirdgyn/viastitching)
- Fork: [nilskiefer/viastitching2.0](https://github.com/nilskiefer/viastitching2.0)
- License: MIT (see `LICENSE`)
