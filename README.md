# ViaStitching

Via Stitching action-plugin for use with KiCAD 6.0+ (updated for KiCad 9 compatibility).

Fill a selected copper area with a pattern of vias.

## When to use this tool

Whenever you need to fill a copper area with vias to improve thermal or current conduction this tool is the answer (yet not the best one probably). The plugin is based on pre-existing areas so you have to define and select one before invoking the plugin.

## Install

As any other KiCAD plugin - ViaStitching must be installed into one of the allowed path, my personal advice is to install it as a user plugin.
To install it as user plugin on Windows systems (KiCAD 7.0) you should put plugins files into:

C:\Users\<user_folder>\Documents\KiCad\7.0\scripting\plugins\viastitching

## KiCad 9 IPC mode (undo/redo-safe backend)

This repo now includes a KiCad 9 IPC plugin manifest (`plugin.json`) and IPC entrypoints:
- `ipc/update_via_array.py`
- `ipc/update_via_array_maximize.py`
- `ipc/remove_via_array.py`
- `ipc/clean_orphan_vias.py`

For KiCad 9 IPC actions:
1. Enable `Preferences -> Plugins -> Enable KiCad API`.
2. Make sure the plugin environment installs `requirements.txt`.
3. Use the IPC actions from the plugin menu.

The ActionPlugin entrypoint (`Tools -> External Plugins -> ViaStitching`) is also available and runs in a single modal action flow, matching the behavior style of mature legacy plugins.

The IPC backend (`ipc/viastitching_ipc.py`) groups each operation into a single KiCad board commit (`begin_commit/push_commit`), so Undo/Redo is coherent for create/remove/update actions.
Plugin ownership/settings are stored in PCB-embedded metadata (not only local plugin files), so reverting PCB commits also reverts array ownership state.
`Update Via Array (Maximize)` now uses dense non-grid candidate packing to maximize via count while respecting overlap checks and edge/pad margins.

## How it works (KiCad 9 IPC)

1. Select one copper zone in PCB Editor.
2. Run `Update Via Array` (or `Update Via Array (Maximize)`).
3. A settings dialog opens for that selected zone (size/drill, spacing/offset, edge margin, pad margin, layer overlap scope, centering, maximize).
4. Confirm with `OK` to apply one transactional update commit.

Notes:
- The zone net is always derived from the selected zone and is read-only.
- In maximize mode, spacing/offset fields are ignored (and disabled in the ActionPlugin dialog). Placement is driven by via geometry plus edge/pad margins.
- If no filled copper is available, the plugin asks whether to rebuild zone copper.
- If user-placed vias exist on the selected zone net inside the zone, the plugin asks whether to replace them.
- `Remove Via Array` removes plugin-owned vias for the selected zone; if user vias are detected in the same zone/net, it asks whether to remove those too.
- `Clean Orphan Vias` removes plugin-owned vias that no longer belong inside their owning zones.
- In the ActionPlugin dialog, options (including `Reset Prompt Choices` and `Clean Orphan Vias`) are in the left-side options panel; bottom-row actions are `Cancel`, `Remove Via Array`, and `OK`.

Ownership and settings are persisted in PCB metadata, so commit/revert in git keeps via-array state coherent with the board revision.

## TODO

Some features still to code:
- [x] Match user units (mm/inches).
- [x] Add clear area function.
- [ ] Draw a better UI (if anyone is willing to contribute please read the following section).
- [x] Collision between new vias and underlying objects: 
   - [x] tracks, 
   - [x] zones,
   - [x] pads,
   - [x] footprint zones,
   - [x] modules,
   - [x] vias.
- [ ] Different fillup patterns/modes (bounding box, centered spiral).
- [x] Avoid placing vias near area edges (define clearance).
- [x] History management (board commit).
- [ ] Localization.
- [x] Support for multiple zones
- [x] Storage of stitching configuration for each individual zone in PCB metadata.
- [ ] Any request?

## Coding notes

If you are willing to make any modification to the GUI (you're welcome) trough __wxFormBuilder__ (```viastitching.fbp``` file) remember to modify this line (around line 25 ```viastitching_gui.py```):
```
self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )
```
In this way:
```
if sys.version_info[0] == 2:
 self.SetSizeHintsSz( wx.DefaultSize, wx.DefaultSize )
else:
 self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )
```
This modification allows the code to work with __Python 2__ (that's the standard KiCAD/Python distribution AFAIK) as long as __Python 3__, please note that you need to ```import sys```. Special thanks to *NilujePerchut* for this hint.

## kicad-action-scripts - ViaStitching plugin similarity

Yes my plugin is pretty similar to this plugin but I'm using a radically different approach in coding. At the time I wrote the first release of my plugin unluckly __jsreynaud__ plugin wasn't working but I bet he will fix it.

## References

Some useful references that helped me coding this plugin:
1. https://sourceforge.net/projects/wxformbuilder/
2. https://wxpython.org/
3. http://docs.kicad-pcb.org/doxygen-python/namespacepcbnew.html
4. https://forum.kicad.info/c/external-plugins
5. https://github.com/KiCad/kicad-source-mirror/blob/master/Documentation/development/pcbnew-plugins.md
6. https://kicad.mmccoo.com/
7. http://docs.kicad-pcb.org/5.1.4/en/pcbnew/pcbnew.html#kicad_scripting_reference


Tool I got inspired by:
- Altium Via Stitching feature!
- https://github.com/jsreynaud/kicad-action-scripts

## Greetings

Hope someone find my work useful or at least *inspiring* to create something else/better.
Special thanks to everyone that contributed to this project:
- [Giulio Borsoi](https://github.com/giulio-borsoi)
- [danwood76](https://github.com/danwood76)
- [NilujePerchut](https://github.com/NilujePerchut)

Last but not least, I would like to thank everyone who shared their knowledge of Python and KiCAD with me: Thanks!
#

Live long and prosper!

That's all folks.

By[t]e{s}
 Weirdgyn
