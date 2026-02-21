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

For KiCad 9:
1. Enable `Preferences -> Plugins -> Enable KiCad API`.
2. Make sure the plugin environment installs `requirements.txt`.
3. Use the IPC actions from the plugin menu.

The old `ActionPlugin` entrypoint is intentionally non-editing now: transactional commit support is not available there on this KiCad build, so all modifying operations are IPC-only.

The IPC backend (`ipc/viastitching_ipc.py`) groups each operation into a single KiCad board commit (`begin_commit/push_commit`), so Undo/Redo is coherent for create/remove/update actions.
Plugin ownership/settings are stored in PCB-embedded metadata (not only local plugin files), so reverting PCB commits also reverts array ownership state.
The IPC placement engine centers via rows inside local discontinuous zone segments for neater arrays; a dedicated `Update Via Array (Maximize)` action runs multi-phase search to pack more vias while respecting edge/pad margins.

## How it works

The workflow is pretty simple: select the area you want to fill (or select an existing stitching group), click on ```Tools->External Plugins->ViaStitching``` or click on ![AddNet icon](viastitching.png?raw=true) toolbar icon: a dilaog like the one below should appear:

![ViaStitching dialog](pictures/viastitching_dialog.png?raw=true "ViaStitching dialog")

The net is now derived from the selected zone and is read-only in the dialog.
The plugin dialog lets you specify via size/drill plus two separate margin controls:
- Edge margin: extra distance from via edge to zone boundary.
- Pad margin: extra spacing used by overlap checks against tracks/pads/vias/zones.
You can also customize vertical/horizontal spacing and offsets.
All controls now include tooltips explaining what they do.
The plugin now also includes a toggle (`Check overlaps on all copper layers`) so you can decide whether overlap checks are global (all copper layers) or limited to the selected zone layer.
`Center local segments` keeps each discontinuous row fragment visually centered.
`Try to maximize vias` runs a phase search to maximize via count while respecting margins.
The most recent settings are remembered and restored when reopening the dialog, including via size/drill, spacing, offsets, edge margin, pad margin, randomize, clear mode, and the overlap-scope toggle.
For safety, plugin-managed vias are tracked per zone by UUID in the PCB file. Remove/update operations only touch vias in that ownership list, so user-placed vias are not modified even if they look identical or are copied from plugin-created geometry.
The `Remove Via Array` button removes only plugin-owned vias and keeps the selected zone/pour.
When you're satisfied with your settings you have just to press __Ok__ and the fillup will begin (I'm assuming __Fill__ action is checked).
If everything goes fine you'll get something like this:

![viastitching result](pictures/viastitching_result.png?raw=true "ViaStitching result")

After stitching is always a good practice to perform a DRC.

As you can see some implanted vias may still overlap with some other PCB elements (tracks, ~~zone, pads, vias~~ etc) at this development stage the removal of conflicting vias is up to the user with future releases the implant process will prevent vias to overlap with other elements.

The default action of the dialog is the __Fill__ action (as you can notice from the radio-button on the bottom) but this plugin is not limited to this function only. __Clear__ action works the in the opposite way: it removes from selected area any vias matching settings (i.e. same net, same size, same drill specified in dialog fields). Beware: __Clear__ will not distinguish vias implanted by __Fill__ from user ones until you check the specific checkbox, and will remove all of them if they match the values entered. If you check __clear only plugin placed vias__ widget the plugin will inspect vias grouped on a specific group and remove only those matching: this can be used as an __Undo__ feature.

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
- [ ] History management (board commit).
- [ ] Localization.
- [x] Support for multiple zones
- [x] Storage of stitching configuration for each individual zone as JSON string in a user layer.
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
