#!/usr/bin/env python

# ViaStitching for pcbnew 
# This is the plugin WX dialog
# (c) Michele Santucci 2019
#
import random
from json import JSONDecodeError
import os
import subprocess
import sys
import time
from datetime import datetime

import wx
import pcbnew
import gettext
import math

from .viastitching_gui import viastitching_gui

numpy_available = False
try:
    import numpy as np
    numpy_available = True
except Exception:
    from math import sqrt, pow
import json

_ = gettext.gettext
__version__ = "0.4"
__plugin_name__ = "ViaStitching"
#__timecode__ = 1972
__viagroupname_base__ = "VIA_STITCHING_GROUP"
__plugin_config_layer_name__ = "plugins.config"
__global_settings_key__ = "__last_used__"
_active_dialog = None
__user_prefs_filename__ = "viastitching_user_prefs.json"
__pref_key_close_previous_window__ = "close_previous_window"
__pref_key_remove_user_vias__ = "remove_user_vias"
__pref_key_replace_user_vias__ = "replace_user_vias"
__pref_key_rebuild_zone_copper__ = "rebuild_zone_copper"
__pref_key_enable_logging__ = "enable_logging"
__debug_log_filename__ = "viastitching_debug.log"
__force_modal_dialog__ = False

GUI_defaults = {"to_units": {0: pcbnew.ToMils, 1: pcbnew.ToMM},
                "from_units": {0: pcbnew.FromMils, 1: pcbnew.FromMM},
                "unit_labels": {0: u"mils", 1: u"mm"},
                "spacing": {0: "40", 1: "1"},
                "offset": {0: "0", 1: "0"}}


def _iter_zones(board):
    if hasattr(board, "Zones"):
        return list(board.Zones())

    zones = []
    if hasattr(board, "GetAreaCount") and hasattr(board, "GetArea"):
        for i in range(board.GetAreaCount()):
            zones.append(board.GetArea(i))
    return zones


def _layer_sequence(layer_set):
    if layer_set is None:
        return []
    if hasattr(layer_set, "Seq"):
        return list(layer_set.Seq())
    return []


def _item_netname(item):
    if hasattr(item, "GetNetname"):
        try:
            return item.GetNetname()
        except Exception:
            return None
    return None


def _item_uuid(item):
    if hasattr(item, "GetUuid"):
        try:
            uuid = item.GetUuid()
            if hasattr(uuid, "AsString"):
                return uuid.AsString()
            return str(uuid)
        except Exception:
            pass
    if hasattr(item, "m_Uuid"):
        try:
            uuid = item.m_Uuid
            if hasattr(uuid, "AsString"):
                return uuid.AsString()
            return str(uuid)
        except Exception:
            pass
    return None


def _zone_signature(zone):
    parts = []
    try:
        parts.append(str(zone.GetLayer()))
    except Exception:
        parts.append("layer:?")
    try:
        parts.append(str(zone.GetNetname()))
    except Exception:
        parts.append("net:?")
    try:
        corners = zone.GetNumCorners()
        parts.append(str(corners))
        for i in range(corners):
            c = zone.GetCornerPosition(i)
            parts.append(f"{int(c.x)}:{int(c.y)}")
    except Exception:
        parts.append("corners:?")
    return "|".join(parts)


def _item_type_name(item):
    try:
        return type(item).__name__
    except Exception:
        return ""


def _is_pcb_via(item):
    if item is None:
        return False
    if hasattr(pcbnew, "PCB_VIA"):
        try:
            if isinstance(item, pcbnew.PCB_VIA):
                return True
        except Exception:
            pass
    return _item_type_name(item) == "PCB_VIA"


def _is_pcb_pad(item):
    if item is None:
        return False
    if hasattr(pcbnew, "PAD"):
        try:
            if isinstance(item, pcbnew.PAD):
                return True
        except Exception:
            pass
    return _item_type_name(item) == "PAD"


def _is_board_obj(board):
    if board is None:
        return False
    return hasattr(board, "GetTracks") and hasattr(board, "GetNetsByName")


def _board_api_usable(board):
    if not _is_board_obj(board):
        return False

    probes = (
        ("GetTracks", lambda b: b.GetTracks()),
        ("GetNetsByName", lambda b: b.GetNetsByName()),
    )

    for name, fn in probes:
        try:
            fn(board)
        except Exception as exc:
            _debug_log(
                f"Board probe failed: method={name} board={_safe_obj_desc(board)} "
                f"error={type(exc).__name__}: {exc}"
            )
            return False
    return True


def _resolve_board(board, retries=8, retry_delay_s=0.08):
    for attempt in range(max(1, int(retries))):
        candidates = []
        if board is not None:
            candidates.append(board)
        try:
            active = pcbnew.GetBoard()
            if active is not None:
                candidates.append(active)
        except Exception:
            pass

        for candidate in candidates:
            if _board_api_usable(candidate):
                if attempt > 0:
                    _debug_log(f"Resolved board after retry #{attempt}: {_safe_obj_desc(candidate)}")
                else:
                    _debug_log(f"Resolved board object: {_safe_obj_desc(candidate)}")
                return candidate

        if hasattr(pcbnew, "BOARD"):
            for candidate in candidates:
                try:
                    cast_board = pcbnew.BOARD(candidate)
                except Exception:
                    continue
                if _board_api_usable(cast_board):
                    if attempt > 0:
                        _debug_log(f"Resolved board via cast after retry #{attempt}: {_safe_obj_desc(cast_board)}")
                    else:
                        _debug_log(f"Resolved board via cast: {_safe_obj_desc(cast_board)}")
                    return cast_board

        if attempt < retries - 1:
            time.sleep(float(retry_delay_s))

    _debug_log("Failed to resolve active board object after retries.")
    return None


def _user_prefs_path():
    return os.path.join(os.path.dirname(__file__), __user_prefs_filename__)


def _debug_log_path():
    return os.path.join(os.path.dirname(__file__), __debug_log_filename__)


def _is_logging_enabled():
    prefs = _read_user_prefs()
    value = prefs.get(__pref_key_enable_logging__)
    if isinstance(value, bool):
        return value
    return True


def _set_logging_enabled(enabled):
    prefs = _read_user_prefs()
    prefs[__pref_key_enable_logging__] = bool(enabled)
    return _write_user_prefs(prefs)


def _debug_log_force(message):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def _debug_log(message):
    if not _is_logging_enabled():
        return
    _debug_log_force(message)


def _open_log_folder():
    folder = os.path.dirname(_debug_log_path())
    try:
        if hasattr(wx, "LaunchDefaultApplication"):
            if wx.LaunchDefaultApplication(folder):
                return True
    except Exception:
        pass

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", folder])
            return True
        if os.name == "nt":
            os.startfile(folder)
            return True
        subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def _show_error_with_log(parent, title, message, context=""):
    if context:
        _debug_log_force(f"ERROR [{context}] {message}")
    else:
        _debug_log_force(f"ERROR {message}")

    prompt = _(
        u"%s\n\nLog file: %s\n\nOpen log folder?"
    ) % (message, _debug_log_path())
    dlg = wx.MessageDialog(parent, prompt, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_ERROR)
    if hasattr(dlg, "SetYesNoLabels"):
        dlg.SetYesNoLabels(_(u"Open Log Folder"), _(u"Close"))
    result = dlg.ShowModal()
    dlg.Destroy()
    if result == wx.ID_YES:
        _open_log_folder()


def _show_info(parent, title, message):
    _debug_log_force(f"INFO [{title}] {message}")
    try:
        wx.MessageBox(message, title)
    except Exception:
        pass


def _safe_obj_desc(obj):
    if obj is None:
        return "None"
    obj_type = type(obj).__name__
    try:
        obj_repr = repr(obj)
    except Exception:
        obj_repr = "<repr failed>"
    if len(obj_repr) > 200:
        obj_repr = obj_repr[:200] + "...(truncated)"
    return f"{obj_type}: {obj_repr}"


def _read_user_prefs():
    path = _user_prefs_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        if isinstance(prefs, dict):
            return prefs
    except Exception:
        pass
    return {}


def _write_user_prefs(prefs):
    if not isinstance(prefs, dict):
        return False
    path = _user_prefs_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


def _clear_user_prefs():
    prefs = _read_user_prefs()
    prompt_keys = [
        __pref_key_close_previous_window__,
        __pref_key_remove_user_vias__,
        __pref_key_replace_user_vias__,
        __pref_key_rebuild_zone_copper__,
    ]

    changed = False
    for key in prompt_keys:
        if key in prefs:
            prefs.pop(key, None)
            changed = True

    if not changed:
        return True

    path = _user_prefs_path()
    try:
        if prefs:
            return _write_user_prefs(prefs)
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception:
        return False


def _get_saved_prompt_choice(key):
    prefs = _read_user_prefs()
    value = prefs.get(key)
    return value if isinstance(value, bool) else None


def _set_saved_prompt_choice(key, value):
    if not isinstance(value, bool):
        return False
    prefs = _read_user_prefs()
    prefs[key] = value
    return _write_user_prefs(prefs)


def _prompt_yes_no_with_memory(parent, title, message, pref_key):
    saved_choice = _get_saved_prompt_choice(pref_key)
    if saved_choice is not None:
        return saved_choice

    style = wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
    remember_choice = False
    result_yes = False

    if hasattr(wx, "RichMessageDialog"):
        dlg = wx.RichMessageDialog(parent, message, title, style)
        if hasattr(dlg, "ShowCheckBox"):
            dlg.ShowCheckBox(_(u"Always use this choice"))
        result_yes = (dlg.ShowModal() == wx.ID_YES)
        if hasattr(dlg, "IsCheckBoxChecked"):
            remember_choice = bool(dlg.IsCheckBoxChecked())
        dlg.Destroy()
    else:
        result_yes = (wx.MessageBox(message, title, style, parent) == wx.YES)

    if remember_choice:
        _set_saved_prompt_choice(pref_key, result_yes)

    return result_yes

class ViaStitchingDialog(viastitching_gui):
    """Class that gathers all the GUI controls."""

    def __init__(self, board, parent=None):
        """Initialize the brand new instance."""

        super(ViaStitchingDialog, self).__init__(parent)
        self.viagroupname = None
        self.SetTitle(_(u"{0} v{1}").format(__plugin_name__, __version__))
        self.Bind(wx.EVT_CLOSE, self.onCloseWindow)
        self.m_btnCancel.Bind(wx.EVT_BUTTON, self.onCloseWindow)
        self.m_btnOk.Bind(wx.EVT_BUTTON, self.onProcessAction)
        self.m_btnClear.Bind(wx.EVT_BUTTON, self.onClearAction)
        if hasattr(self, "m_btnCleanOrphans"):
            self.m_btnCleanOrphans.Bind(wx.EVT_BUTTON, self.onCleanOrphansAction)
        if hasattr(self, "m_chkDebugLogging"):
            self.m_chkDebugLogging.Bind(wx.EVT_CHECKBOX, self.onToggleLogging)
        if hasattr(self, "m_btnResetPrompts"):
            self.m_btnResetPrompts.Bind(wx.EVT_BUTTON, self.onResetPromptChoices)
        self.board = _resolve_board(board)
        if self.board is None:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(u"Unable to access active board. Close and reopen PCB Editor, then retry."),
                context="init_board"
            )
            self.Destroy()
            return
        self.randomize = False
        self.pcb_group = None
        self.pad_margin = 0
        self.board_edges = []
        self.config_layer = 0
        self.config_textbox = None
        self.area = None
        self.net = None
        self.config = {}
        self.include_other_layers = True
        self.target_layers = set()
        self.pruned_stale_vias = 0
        self.owned_via_ids = set()
        self.last_fill_stats = {}
        self.last_commit_error = ""
        self.has_valid_selection = False
        self._last_selection_signature = None
        self._last_orphan_scan = {
            "orphan_vias": [],
            "orphan_ids": set(),
            "missing_ids": set(),
            "counts_by_net": {},
        }
        self.selection_timer = wx.Timer(self)
        self.parent_window = parent
        self._action_in_progress = False
        self._selection_timer_was_running = False

        if hasattr(self, "m_chkDebugLogging"):
            self.m_chkDebugLogging.SetValue(_is_logging_enabled())

        _debug_log("ViaStitching dialog opened.")

        if self.parent_window is not None:
            try:
                self.parent_window.Bind(wx.EVT_CLOSE, self.onParentWindowClose)
            except Exception:
                pass

        self.getConfigLayer()

        drawings = []
        if hasattr(self.board, "GetDrawings"):
            try:
                drawings = self.board.GetDrawings()
            except Exception as exc:
                _debug_log(
                    "GetDrawings failed during init: "
                    f"board={_safe_obj_desc(self.board)} "
                    f"error={type(exc).__name__}: {exc}"
                )
                _show_error_with_log(
                    self,
                    _(u"ViaStitching"),
                    _(u"Unable to read board drawings from the current KiCad board object."),
                    context="init_get_drawings",
                )
                self.Destroy()
                return
        for d in drawings:
            layer_name = self.GetLayerName(d)
            if layer_name == 'Edge.Cuts':
                self.board_edges.append(d)
            if hasattr(d, "GetText"):
                try:
                    new_config = json.loads(d.GetText())
                    if isinstance(new_config, dict) and __plugin_name__ in new_config:
                        self.config_textbox = d
                        self.config = new_config
                except (JSONDecodeError, AttributeError):
                    pass


        # Use the same unit set int PCBNEW
        self.ToUserUnit = None
        self.FromUserUnit = None
        units_mode = pcbnew.GetUserUnits()
        if units_mode == -1:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Not a valid frame"), context="init_units")
            self.Destroy()
            return

        # Check selected area, but keep dialog open even when no valid zone is selected.
        self.GetAreaConfig()
        self.has_valid_selection = bool(self.area is not None and self.net)
        _debug_log(
            f"Init selection state: has_valid_selection={self.has_valid_selection} "
            f"net={self.net if self.net else '<none>'}"
        )

        # Populate net box (blank when no valid selected zone/net).
        self.PopulateNets()

        self.ToUserUnit = GUI_defaults["to_units"][units_mode]
        self.FromUserUnit = GUI_defaults["from_units"][units_mode]
        self.m_lblUnit1.SetLabel(_(GUI_defaults["unit_labels"][units_mode]))
        self.m_lblUnit2.SetLabel(_(GUI_defaults["unit_labels"][units_mode]))
        if hasattr(self, "m_lblUnit3"):
            self.m_lblUnit3.SetLabel(_(GUI_defaults["unit_labels"][units_mode]))
        if hasattr(self, "m_lblUnit4"):
            self.m_lblUnit4.SetLabel(_(GUI_defaults["unit_labels"][units_mode]))
        if hasattr(self, "m_lblUnit5"):
            self.m_lblUnit5.SetLabel(_(GUI_defaults["unit_labels"][units_mode]))

        zone_name = self.area.GetZoneName() if self.area is not None else ""
        zone_defaults = self.config.get(zone_name, {}) if zone_name else {}
        global_defaults = self.config.get(__global_settings_key__, {})
        self.LoadOwnedViasForZone(self.area)
        defaults = {}
        defaults.update(global_defaults)
        defaults.update(zone_defaults)
        if self.area is not None:
            self.viagroupname = __viagroupname_base__ + self.area.GetZoneName()

            # Search trough groups
            for group in self.GetGroups():
                if group.GetName() == self.viagroupname:
                    self.pcb_group = group
            self.RefreshOwnedViasState()
        else:
            self.viagroupname = None

        self.m_txtVSpacing.SetValue(defaults.get("VSpacing", GUI_defaults["spacing"][units_mode]))
        self.m_txtHSpacing.SetValue(defaults.get("HSpacing", GUI_defaults["spacing"][units_mode]))
        self.m_txtVOffset.SetValue(defaults.get("VOffset", GUI_defaults["offset"][units_mode]))
        self.m_txtHOffset.SetValue(defaults.get("HOffset", GUI_defaults["offset"][units_mode]))
        legacy_clearance = defaults.get("Clearance", "0")
        self.m_txtClearance.SetValue(defaults.get("EdgeMargin", legacy_clearance))
        self.m_txtPadMargin.SetValue(defaults.get("PadMargin", legacy_clearance))
        self.m_chkRandomize.SetValue(defaults.get("Randomize", False))
        self.m_chkClearOwn.SetValue(defaults.get("ClearOwn", True))
        self.m_chkClearOwn.Hide()
        self.Layout()
        self.m_chkIncludeOtherLayers.SetValue(defaults.get("IncludeOtherLayers", True))
        if hasattr(self, "m_chkCenterSegments"):
            self.m_chkCenterSegments.SetValue(defaults.get("CenterSegments", True))
        if hasattr(self, "m_chkMaximizeVias"):
            self.m_chkMaximizeVias.SetValue(defaults.get("MaximizeVias", False))
        self.include_other_layers = self.m_chkIncludeOtherLayers.GetValue()

        # Get default Vias dimensions
        via_size_default = defaults.get("ViaSize")
        via_drill_default = defaults.get("ViaDrill")
        via_dim_list = self.board.GetViasDimensionsList() if hasattr(self.board, "GetViasDimensionsList") else None

        if (via_size_default is None or via_drill_default is None) and via_dim_list:
            via_dims = via_dim_list.pop()
            via_size_default = self.ToUserUnit(via_dims.m_Diameter)
            via_drill_default = self.ToUserUnit(via_dims.m_Drill)
            via_dim_list.push_back(via_dims)

        if via_size_default is None or via_drill_default is None:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(u"Please set via drill/size in board"),
                context="init_via_defaults"
            )
            self.Destroy()
            return

        self.m_txtViaSize.SetValue(str(via_size_default))
        self.m_txtViaDrillSize.SetValue(str(via_drill_default))

        if self.net:
            index = self.m_cbNet.FindString(self.net)
            if index != wx.NOT_FOUND:
                self.m_cbNet.Select(index)
        else:
            self.m_cbNet.SetValue("")
        self.m_cbNet.Enable(False)
        self.overlappings = None
        self.SetTooltips()
        self.UpdateActionButtons()

        self.Bind(wx.EVT_TIMER, self.onSelectionPoll, self.selection_timer)
        self.selection_timer.Start(600)

    def SetTooltips(self):
        tips = [
            (self.m_lblNetName, _(u"Net is taken from the selected zone.")),
            (self.m_cbNet, _(u"Read-only: derived from selected zone net.")),
            (self.m_lblVia, _(u"Via outer diameter and drill size.")),
            (self.m_txtViaSize, _(u"Via outer diameter.")),
            (self.m_txtViaDrillSize, _(u"Via drill diameter. Must be smaller than via size.")),
            (self.m_lblSpacing, _(u"Grid spacing between vias: vertical / horizontal.")),
            (self.m_txtVSpacing, _(u"Vertical spacing between via centers.")),
            (self.m_txtHSpacing, _(u"Horizontal spacing between via centers.")),
            (self.m_lblOffset, _(u"Grid offsets: vertical / horizontal.")),
            (self.m_txtVOffset, _(u"Vertical offset of the via grid.")),
            (self.m_txtHOffset, _(u"Horizontal offset of the via grid.")),
            (self.m_staticText6, _(u"Extra distance from via edge to zone boundary.")),
            (self.m_txtClearance, _(u"Edge margin: via edge to zone boundary distance.")),
            (self.m_staticTextPadMargin, _(u"Extra distance from vias to pads/tracks/vias/zones during overlap checks.")),
            (self.m_txtPadMargin, _(u"Pad margin: additional spacing used in overlap rejection.")),
            (self.m_chkClearOwn, _(u"Internal compatibility option.")),
            (self.m_chkRandomize, _(u"Apply small random jitter to each grid point.")),
            (self.m_chkIncludeOtherLayers, _(u"If enabled, reject vias that collide with copper objects on any copper layer. Disable to only check the selected zone layer.")),
            (self.m_chkCenterSegments, _(u"If enabled, each reachable segment in a discontinuous row is centered for a neater pattern.")),
            (self.m_chkMaximizeVias, _(u"Try multiple grid phases and segment packing to place as many vias as possible while respecting margins.")),
            (self.m_chkDebugLogging, _(u"Write detailed runtime logs to viastitching_debug.log in the plugin folder.")),
            (self.m_btnOk, _(u"Apply stitching with current parameters.")),
            (self.m_btnClear, _(u"Remove plugin-owned vias. If matching user vias are found on this zone net, you can choose to remove them too.")),
            (self.m_btnCleanOrphans, _(u"Remove plugin-owned vias that are no longer inside their configured zone.")),
            (self.m_btnResetPrompts, _(u"Clear saved popup decisions (always-use choices) and restore prompt behavior.")),
            (self.m_btnCancel, _(u"Close without applying changes.")),
        ]

        for control, tip in tips:
            if control is not None:
                control.SetToolTip(tip)

    def GetGroups(self):
        if hasattr(self.board, "Groups"):
            return list(self.board.Groups())
        return []

    def NewBoardCommit(self):
        self.last_commit_error = ""
        attempts = []

        known_names = ["BOARD_COMMIT", "PCB_COMMIT", "COMMIT"]
        extra_names = []
        try:
            extra_names = [name for name in dir(pcbnew) if "COMMIT" in name and name not in known_names]
        except Exception:
            extra_names = []
        class_names = known_names + sorted(extra_names)

        constructors = []
        for class_name in class_names:
            if not hasattr(pcbnew, class_name):
                continue
            cls = getattr(pcbnew, class_name)
            if not callable(cls):
                continue
            constructors.append((class_name, "board", lambda cls=cls: cls(self.board)))
            constructors.append((class_name, "empty", lambda cls=cls: cls()))

        for class_name, arg_mode, ctor in constructors:
            try:
                commit = ctor()
                if commit is None:
                    attempts.append(f"{class_name}({arg_mode}) -> returned None")
                    continue
                attempts.append(f"{class_name}({arg_mode}) -> OK [{type(commit).__name__}]")
                _debug_log("Undo commit init success: " + attempts[-1])
                return commit
            except Exception as e:
                attempts.append(f"{class_name}({arg_mode}) -> {type(e).__name__}: {e}")

        if not attempts:
            attempts.append("No commit classes found in pcbnew module.")

        self.last_commit_error = "\n".join(attempts)
        _debug_log(
            "Undo commit init failed.\n"
            f"Board: {_safe_obj_desc(self.board)}\n"
            f"Attempts:\n{self.last_commit_error}"
        )
        return None

    def CommitAdd(self, commit, item):
        if commit is None or item is None:
            return
        for method in ("Add", "Added", "AddItem"):
            if not hasattr(commit, method):
                continue
            try:
                getattr(commit, method)(item)
                return
            except Exception:
                pass
        _debug_log(
            f"CommitAdd: no usable method for commit={_safe_obj_desc(commit)} "
            f"item={_safe_obj_desc(item)}"
        )

    def CommitRemove(self, commit, item):
        if commit is None or item is None:
            return
        for method in ("Remove", "Removed", "RemoveItem"):
            if not hasattr(commit, method):
                continue
            try:
                getattr(commit, method)(item)
                return
            except Exception:
                pass
        _debug_log(
            f"CommitRemove: no usable method for commit={_safe_obj_desc(commit)} "
            f"item={_safe_obj_desc(item)}"
        )

    def CommitModify(self, commit, item):
        if commit is None or item is None:
            return
        for method in ("Modify", "Modified", "ModifyItem", "Change", "Changed"):
            if not hasattr(commit, method):
                continue
            try:
                getattr(commit, method)(item)
                return
            except Exception:
                pass
        _debug_log(
            f"CommitModify: no usable method for commit={_safe_obj_desc(commit)} "
            f"item={_safe_obj_desc(item)}"
        )

    def CommitPush(self, commit, message):
        if commit is None:
            return
        for method in ("Push", "Commit", "Submit"):
            if not hasattr(commit, method):
                continue
            fn = getattr(commit, method)
            try:
                fn(message)
                return
            except TypeError:
                try:
                    fn()
                    return
                except Exception:
                    pass
            except Exception:
                pass
        _debug_log(
            f"CommitPush failed: methods not usable for commit={_safe_obj_desc(commit)} "
            f"message={message}"
        )

    def ShowUndoInitError(self, context):
        details = self.last_commit_error or "No constructor details captured."
        _debug_log(f"Undo transaction unavailable during {context}.\n{details}")
        _show_error_with_log(
            self,
            _(u"ViaStitching"),
            _(
                u"Unable to start KiCad undo transaction. Operation canceled.\n\n"
                u"Context: %s"
            ) % context,
            context="undo_init"
        )

    def LogNoCommitBackend(self, context):
        details = self.last_commit_error or "No constructor details captured."
        _debug_log(
            f"No commit backend available in {context}. "
            "Operation canceled to avoid unsafe non-undoable edits.\n"
            f"{details}"
        )

    def RequireUndoBackend(self, context, show_popup=True):
        commit = self.NewBoardCommit()
        if commit is not None:
            return commit

        self.LogNoCommitBackend(context)
        if show_popup:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(
                    u"Proper undo/redo support is unavailable in this legacy action-plugin API on your KiCad build.\n\n"
                    u"To avoid board corruption/crashes, this operation was canceled.\n\n"
                    u"Use the KiCad 9 IPC actions instead:\n"
                    u" - Update Via Array\n"
                    u" - Remove Via Array\n"
                    u" - Clean Orphan Vias\n\n"
                    u"Also ensure: Preferences -> Plugins -> Enable KiCad API"
                ),
                context=f"undo_required_{context}"
            )
        return None

    def CloseDialog(self, modal_code=wx.ID_CANCEL):
        global _active_dialog
        _active_dialog = None
        try:
            if hasattr(self, "selection_timer") and self.selection_timer is not None:
                if self.selection_timer.IsRunning():
                    self.selection_timer.Stop()
        except Exception:
            pass
        if self.parent_window is not None:
            try:
                self.parent_window.Unbind(wx.EVT_CLOSE, handler=self.onParentWindowClose)
            except Exception:
                pass

        try:
            if self.IsModal():
                self.EndModal(modal_code)
                return
        except Exception:
            pass

        try:
            self.Destroy()
        except Exception:
            pass

    def GetViaParentGroup(self, via):
        if via is None or not hasattr(via, "GetParentGroup"):
            return None
        try:
            return via.GetParentGroup()
        except Exception:
            return None

    def RefreshOwnedViasState(self):
        if self.viagroupname:
            self.pcb_group = self.FindGroupByName(self.viagroupname)

        existing_ids = set()
        group_ids = set()
        for item in self.board.GetTracks():
            if not _is_pcb_via(item):
                continue
            via_uuid = _item_uuid(item)
            if via_uuid:
                existing_ids.add(via_uuid)
            parent_group = self.GetViaParentGroup(item)
            if parent_group is not None and via_uuid:
                try:
                    if parent_group.GetName() == self.viagroupname:
                        group_ids.add(via_uuid)
                except Exception:
                    pass

        if self.owned_via_ids:
            self.owned_via_ids &= existing_ids
        self.owned_via_ids |= group_ids

    def LoadOwnedViasForZone(self, zone=None):
        if zone is None:
            zone = self.area
        if zone is None:
            self.owned_via_ids = set()
            return

        zone_name = ""
        try:
            zone_name = zone.GetZoneName()
        except Exception:
            zone_name = ""

        zone_cfg = self.config.get(zone_name, {}) if zone_name else {}
        owned = zone_cfg.get("OwnedVias", []) if isinstance(zone_cfg, dict) else []
        if isinstance(owned, list):
            self.owned_via_ids = {str(v) for v in owned if v}
        else:
            self.owned_via_ids = set()
        self.RefreshOwnedViasState()

    def CountUserNetViasInZone(self):
        if self.area is None or not self.net:
            return 0
        netcode = self.board.GetNetcodeFromNetname(self.net)
        if netcode < 0:
            return 0

        count = 0
        for item in self.board.GetTracks():
            if not _is_pcb_via(item):
                continue
            try:
                if item.GetNetCode() != netcode:
                    continue
            except Exception:
                continue
            via_uuid = _item_uuid(item)
            if via_uuid and via_uuid in self.owned_via_ids:
                continue
            if self.IsInsideSelectedZone(item.GetPosition()):
                count += 1
        return count

    def CountExistingOwnedVias(self):
        self.RefreshOwnedViasState()
        if not self.owned_via_ids:
            return 0
        count = 0
        for item in self.board.GetTracks():
            if not _is_pcb_via(item):
                continue
            via_uuid = _item_uuid(item)
            if via_uuid and via_uuid in self.owned_via_ids:
                count += 1
        return count

    def IsSelectionValid(self):
        self.has_valid_selection = bool(self.area is not None and self.net)
        return self.has_valid_selection

    def GetZoneNetFromConfig(self, zone_name, zone_cfg=None, zone_obj=None):
        if zone_obj is None:
            zone_obj = self.FindZoneByName(zone_name)
        if zone_obj is not None:
            try:
                net_name = zone_obj.GetNetname()
                if net_name:
                    return net_name
            except Exception:
                pass

        if not isinstance(zone_cfg, dict):
            return ""
        signature = zone_cfg.get("ZoneSignature", "")
        if not isinstance(signature, str):
            return ""
        parts = signature.split("|")
        if len(parts) < 2:
            return ""
        if parts[1].startswith("net:"):
            return parts[1][4:]
        return parts[1]

    def BuildViaUuidIndex(self):
        via_by_uuid = {}
        for item in self.board.GetTracks():
            if not _is_pcb_via(item):
                continue
            via_uuid = _item_uuid(item)
            if via_uuid:
                via_by_uuid[via_uuid] = item
        return via_by_uuid

    def ScanOrphanOwnedVias(self):
        entries = self.GetZoneConfigEntries()
        via_by_uuid = self.BuildViaUuidIndex()

        orphan_vias = []
        orphan_ids = set()
        missing_ids = set()
        counts_by_net = {}

        for zone_name, zone_cfg in entries.items():
            owned = zone_cfg.get("OwnedVias", [])
            if not isinstance(owned, list):
                continue

            zone_obj = self.FindZoneByName(zone_name)
            zone_net = self.GetZoneNetFromConfig(zone_name, zone_cfg=zone_cfg, zone_obj=zone_obj)

            for raw_uuid in owned:
                via_uuid = str(raw_uuid) if raw_uuid else ""
                if not via_uuid:
                    continue

                via = via_by_uuid.get(via_uuid)
                if via is None:
                    missing_ids.add(via_uuid)
                    continue

                stale = False
                if zone_obj is None:
                    stale = True
                else:
                    via_radius = via.GetWidth() / 2 if hasattr(via, "GetWidth") else 0
                    if not self.IsPointInsideZoneWithMargin(via.GetPosition(), via_radius, zone=zone_obj):
                        stale = True

                if stale and via_uuid not in orphan_ids:
                    orphan_ids.add(via_uuid)
                    orphan_vias.append(via)
                    via_net = _item_netname(via) or zone_net or _(u"(no net)")
                    counts_by_net[via_net] = counts_by_net.get(via_net, 0) + 1

        return {
            "orphan_vias": orphan_vias,
            "orphan_ids": orphan_ids,
            "missing_ids": missing_ids,
            "counts_by_net": counts_by_net,
        }

    def CleanupOwnedViaConfigIds(self, remove_ids=None, missing_ids=None):
        remove_ids = set(remove_ids or [])
        missing_ids = set(missing_ids or [])
        changed = False

        for _, zone_cfg in self.GetZoneConfigEntries().items():
            owned = zone_cfg.get("OwnedVias", [])
            if not isinstance(owned, list):
                continue

            filtered = []
            for raw_uuid in owned:
                via_uuid = str(raw_uuid) if raw_uuid else ""
                if not via_uuid:
                    continue
                if via_uuid in remove_ids or via_uuid in missing_ids:
                    continue
                filtered.append(via_uuid)

            filtered = sorted(set(filtered))
            if filtered != [str(v) for v in owned if v]:
                zone_cfg["OwnedVias"] = filtered
                changed = True

        return changed

    def SaveConfigBlob(self, commit=None):
        if not isinstance(self.config, dict):
            self.config = {}
        self.config[__plugin_name__] = __version__
        self.EnsureConfigTextbox(commit=commit)
        self.CommitModify(commit, self.config_textbox)
        self.config_textbox.SetText(json.dumps(self.config, indent=2))

    def UpdateActionButtons(self, refresh_orphan_scan=True):
        selection_ok = self.IsSelectionValid()
        self.m_btnOk.Enable(selection_ok)

        if selection_ok:
            owned_count = self.CountExistingOwnedVias()
            self.m_btnClear.Enable(owned_count > 0)
            self.m_btnClear.SetToolTip(
                _(u"Remove plugin-owned vias. If matching user vias are found on this zone net, you can choose to remove them too.")
                if owned_count > 0
                else _(u"No plugin-owned via array exists for this selected zone/group.")
            )
        else:
            self.m_btnClear.Enable(False)
            self.m_btnClear.SetToolTip(_(u"Select a filled copper zone with a net to enable removing zone via arrays."))
            self.m_btnOk.SetToolTip(_(u"Select a filled copper zone with a net to enable stitching."))

        if hasattr(self, "m_btnCleanOrphans"):
            if refresh_orphan_scan:
                self._last_orphan_scan = self.ScanOrphanOwnedVias()
            scan = self._last_orphan_scan
            orphan_count = len(scan["orphan_vias"])
            missing_count = len(scan["missing_ids"])
            can_clean = (orphan_count > 0) or (missing_count > 0)
            self.m_btnCleanOrphans.Enable(can_clean)
            if can_clean:
                self.m_btnCleanOrphans.SetToolTip(
                    _(u"Remove %d orphan plugin vias and clean %d stale owned-via IDs from config.")
                    % (orphan_count, missing_count)
                )
            else:
                self.m_btnCleanOrphans.SetToolTip(
                    _(u"No orphan plugin vias detected.")
                )

    def PromptRemoveUserNetVias(self, count):
        title = _(u"User Vias Detected")
        message = _(
            u"Detected %d user-placed vias on the selected zone net inside this zone.\n\n"
            u"Remove those vias too?"
        ) % count
        return _prompt_yes_no_with_memory(
            self, title, message, __pref_key_remove_user_vias__
        )

    def PromptReplaceUserNetVias(self, count):
        title = _(u"User Vias Detected")
        message = _(
            u"Detected %d user-placed vias on the selected zone net inside this zone.\n\n"
            u"Replace those vias with plugin vias?"
        ) % count
        return _prompt_yes_no_with_memory(
            self, title, message, __pref_key_replace_user_vias__
        )

    def SafeRemoveVia(self, via):
        if via is None:
            return
        if hasattr(via, "IsSelected") and via.IsSelected():
            try:
                if hasattr(via, "ClearSelected"):
                    via.ClearSelected()
                elif hasattr(via, "SetSelected"):
                    via.SetSelected(False)
            except Exception:
                pass
        self.board.Remove(via)

    def SafeRemoveViaWithCommit(self, via, commit):
        parent_group = self.GetViaParentGroup(via)
        if parent_group is not None:
            self.CommitModify(commit, parent_group)
        self.CommitRemove(commit, via)
        self.SafeRemoveVia(via)

    def ClearEditorSelection(self):
        try:
            if hasattr(self.board, "ClearSelection"):
                self.board.ClearSelection()
        except Exception:
            pass

        for group in self.GetGroups():
            if hasattr(group, "IsSelected") and group.IsSelected():
                try:
                    if hasattr(group, "ClearSelected"):
                        group.ClearSelected()
                    elif hasattr(group, "SetSelected"):
                        group.SetSelected(False)
                except Exception:
                    pass
        for item in self.board.GetTracks():
            if hasattr(item, "IsSelected") and item.IsSelected():
                try:
                    if hasattr(item, "ClearSelected"):
                        item.ClearSelected()
                    elif hasattr(item, "SetSelected"):
                        item.SetSelected(False)
                except Exception:
                    pass
        for zone in _iter_zones(self.board):
            if hasattr(zone, "IsSelected") and zone.IsSelected():
                try:
                    if hasattr(zone, "ClearSelected"):
                        zone.ClearSelected()
                    elif hasattr(zone, "SetSelected"):
                        zone.SetSelected(False)
                except Exception:
                    pass

    def EnsureZoneInGroup(self, commit=None):
        if self.pcb_group is None or self.area is None:
            return
        if hasattr(self.area, "GetParentGroup"):
            parent = self.area.GetParentGroup()
            if parent is not None and parent.GetName() == self.viagroupname:
                return
        try:
            self.CommitModify(commit, self.pcb_group)
            self.CommitModify(commit, self.area)
            self.pcb_group.AddItem(self.area)
        except Exception:
            pass

    def FindGroupByName(self, name):
        for group in self.GetGroups():
            if group.GetName() == name:
                return group
        return None

    def RemoveCurrentStitchGroup(self, commit=None, push_commit=True):
        group = self.pcb_group
        if group is None and self.viagroupname:
            group = self.FindGroupByName(self.viagroupname)
        if group is None:
            _debug_log("RemoveCurrentStitchGroup: no group found")
            return False

        self.ClearEditorSelection()

        try:
            if hasattr(group, "RemoveItem") and self.area is not None:
                try:
                    self.CommitModify(commit, group)
                    self.CommitModify(commit, self.area)
                    group.RemoveItem(self.area)
                except Exception:
                    pass

            self.CommitRemove(commit, group)
            self.board.Remove(group)
            if push_commit:
                self.CommitPush(commit, "ViaStitching: Remove Group")
            if group == self.pcb_group:
                self.pcb_group = None
            self.ClearEditorSelection()
            _debug_log(f"RemoveCurrentStitchGroup: removed group={group.GetName() if hasattr(group, 'GetName') else '<unknown>'}")
            return True
        except Exception:
            self.ClearEditorSelection()
            _debug_log("RemoveCurrentStitchGroup: failed with exception")
            return False

    def FindZoneByName(self, zone_name):
        for zone in _iter_zones(self.board):
            if zone.GetZoneName() == zone_name:
                return zone
        return None

    def GetSelectedStitchZoneFromGroup(self):
        for group in self.GetGroups():
            if not hasattr(group, "IsSelected") or not group.IsSelected():
                continue
            group_name = group.GetName()
            if not group_name.startswith(__viagroupname_base__):
                continue
            zone_name = group_name[len(__viagroupname_base__):]
            zone = self.FindZoneByName(zone_name)
            if zone is not None:
                return zone

        for item in self.board.GetTracks():
            if not hasattr(item, "IsSelected") or not item.IsSelected():
                continue
            group = item.GetParentGroup() if hasattr(item, "GetParentGroup") else None
            if group is None:
                continue
            group_name = group.GetName()
            if not group_name.startswith(__viagroupname_base__):
                continue
            zone_name = group_name[len(__viagroupname_base__):]
            zone = self.FindZoneByName(zone_name)
            if zone is not None:
                return zone
        return None

    def GetLayerName(self, item):
        if hasattr(item, "GetLayerName"):
            try:
                return item.GetLayerName()
            except Exception:
                pass
        layer = None
        if hasattr(item, "GetLayer"):
            layer = item.GetLayer()
        if layer is None:
            return ""
        if hasattr(self.board, "GetLayerName"):
            try:
                return self.board.GetLayerName(layer)
            except Exception:
                return ""
        return ""

    def GetItemLayers(self, item):
        if hasattr(item, "GetLayerSet"):
            return set(_layer_sequence(item.GetLayerSet()))
        if hasattr(item, "GetLayer"):
            return {item.GetLayer()}
        return set()

    def IsCopperLayerId(self, layer):
        if layer is None:
            return False

        undefined_layer = getattr(pcbnew, "UNDEFINED_LAYER", None)
        if undefined_layer is not None and layer == undefined_layer:
            return False

        if hasattr(self.board, "IsCopperLayer"):
            try:
                return bool(self.board.IsCopperLayer(layer))
            except Exception:
                pass

        if hasattr(pcbnew, "IsCopperLayer"):
            try:
                return bool(pcbnew.IsCopperLayer(layer))
            except Exception:
                pass

        layer_name = ""
        if hasattr(self.board, "GetLayerName"):
            try:
                layer_name = self.board.GetLayerName(layer) or ""
            except Exception:
                layer_name = ""

        if not layer_name:
            return False
        if layer_name.lower() == "undefined":
            return False
        return layer_name.endswith(".Cu") or layer_name in ("F.Cu", "B.Cu")

    def GetZoneHitTestLayers(self, zone=None):
        if zone is None:
            zone = self.area
        if zone is None:
            return []

        layers = []
        seen = set()

        def _add_layer(layer):
            if not self.IsCopperLayerId(layer):
                return
            if layer in seen:
                return
            seen.add(layer)
            layers.append(layer)

        if hasattr(zone, "GetLayer"):
            try:
                _add_layer(zone.GetLayer())
            except Exception:
                pass

        if hasattr(zone, "GetLayerSet"):
            for layer in _layer_sequence(zone.GetLayerSet()):
                _add_layer(layer)

        return layers

    def GetZoneLayers(self, zone):
        return set(self.GetZoneHitTestLayers(zone))

    def GetZoneHitTestLayer(self):
        zone_layers = self.GetZoneHitTestLayers(self.area)
        if not zone_layers:
            return None
        return zone_layers[0]

    def IsInsideSelectedZone(self, point):
        for layer in self.GetZoneHitTestLayers(self.area):
            if self.area.HitTestFilledArea(layer, point, 0):
                return True
        return False

    def IsPointInsideZoneWithMargin(self, point, margin, zone=None):
        if zone is None:
            zone = self.area
        if zone is None:
            return False

        layers = self.GetZoneHitTestLayers(zone)
        if not layers:
            return False

        for layer in layers:
            if not zone.HitTestFilledArea(layer, point, 0):
                continue

            if margin <= 0:
                return True

            sample_count = 32
            layer_ok = True
            for i in range(sample_count):
                angle = (2.0 * math.pi * i) / sample_count
                px = point.x + (margin * math.cos(angle))
                py = point.y + (margin * math.sin(angle))
                if not zone.HitTestFilledArea(layer, self.ToBoardPoint(px, py), 0):
                    layer_ok = False
                    break
            if layer_ok:
                return True
        return False

    def PruneGroupedViasOutsideZone(self, commit=None):
        if not self.owned_via_ids:
            return 0

        to_remove = []
        removed_ids = set()
        for item in list(self.board.GetTracks()):
            if not _is_pcb_via(item):
                continue

            via_uuid = _item_uuid(item)
            if not via_uuid or via_uuid not in self.owned_via_ids:
                continue

            via_radius = item.GetWidth() / 2
            if not self.IsPointInsideZoneWithMargin(item.GetPosition(), via_radius):
                to_remove.append(item)
                removed_ids.add(via_uuid)

        for via in to_remove:
            if commit is not None:
                self.SafeRemoveViaWithCommit(via, commit)
            else:
                self.SafeRemoveVia(via)

        removed = len(to_remove)

        if removed_ids:
            self.owned_via_ids -= removed_ids
        self.UpdateActionButtons()
        return removed

    def IsOnTargetLayers(self, item):
        if self.include_other_layers:
            return True
        item_layers = self.GetItemLayers(item)
        if not item_layers:
            return True
        return bool(item_layers.intersection(self.target_layers))

    def ToBoardPoint(self, x, y):
        px = int(round(x))
        py = int(round(y))
        if hasattr(pcbnew, "VECTOR2I"):
            return pcbnew.VECTOR2I(px, py)
        if hasattr(pcbnew, "wxPoint"):
            return pcbnew.wxPoint(px, py)
        raise RuntimeError("Unsupported KiCad point type")

    def ParseAndValidateInputs(self):
        try:
            inputs = {
                "drillsize": self.FromUserUnit(float(self.m_txtViaDrillSize.GetValue())),
                "viasize": self.FromUserUnit(float(self.m_txtViaSize.GetValue())),
                "step_x": self.FromUserUnit(float(self.m_txtHSpacing.GetValue())),
                "step_y": self.FromUserUnit(float(self.m_txtVSpacing.GetValue())),
                "offset_x": self.FromUserUnit(float(self.m_txtHOffset.GetValue())),
                "offset_y": self.FromUserUnit(float(self.m_txtVOffset.GetValue())),
                "edge_margin": self.FromUserUnit(float(self.m_txtClearance.GetValue())),
                "pad_margin": self.FromUserUnit(float(self.m_txtPadMargin.GetValue())),
            }
        except ValueError:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Please enter valid numeric values."), context="validate_numeric")
            return None

        if inputs["step_x"] <= 0 or inputs["step_y"] <= 0:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Spacing values must be greater than 0."), context="validate_spacing")
            return None
        if inputs["viasize"] <= 0 or inputs["drillsize"] <= 0:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Via size and drill must be greater than 0."), context="validate_via_positive")
            return None
        if inputs["drillsize"] >= inputs["viasize"]:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Via drill must be smaller than via size."), context="validate_drill_lt_via")
            return None
        if inputs["edge_margin"] < 0:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Edge margin cannot be negative."), context="validate_edge_margin")
            return None
        if inputs["pad_margin"] < 0:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Pad margin cannot be negative."), context="validate_pad_margin")
            return None
        _debug_log(f"Parsed inputs: {inputs}")
        return inputs

    def BuildZoneConfig(self):
        return {
            "HSpacing": self.m_txtHSpacing.GetValue(),
            "VSpacing": self.m_txtVSpacing.GetValue(),
            "HOffset": self.m_txtHOffset.GetValue(),
            "VOffset": self.m_txtVOffset.GetValue(),
            "EdgeMargin": self.m_txtClearance.GetValue(),
            "PadMargin": self.m_txtPadMargin.GetValue(),
            "Clearance": self.m_txtClearance.GetValue(),
            "ViaSize": self.m_txtViaSize.GetValue(),
            "ViaDrill": self.m_txtViaDrillSize.GetValue(),
            "Randomize": self.m_chkRandomize.GetValue(),
            "ClearOwn": self.m_chkClearOwn.GetValue(),
            "IncludeOtherLayers": self.m_chkIncludeOtherLayers.GetValue(),
            "CenterSegments": self.m_chkCenterSegments.GetValue() if hasattr(self, "m_chkCenterSegments") else True,
            "MaximizeVias": self.m_chkMaximizeVias.GetValue() if hasattr(self, "m_chkMaximizeVias") else False,
            "ZoneSignature": _zone_signature(self.area),
            "OwnedVias": sorted(self.owned_via_ids),
        }

    def BuildLastUsedConfig(self):
        config = self.BuildZoneConfig()
        config.pop("OwnedVias", None)
        config.pop("ZoneSignature", None)
        config.update(
            {
                "ViaSize": self.m_txtViaSize.GetValue(),
                "ViaDrill": self.m_txtViaDrillSize.GetValue(),
                "ClearOwn": self.m_chkClearOwn.GetValue(),
            }
        )
        return config

    def EnsureConfigTextbox(self, commit=None):
        if self.config_textbox is not None:
            return

        if not isinstance(self.config, dict):
            self.config = {}
        self.config[__plugin_name__] = __version__
        title_block = pcbnew.PCB_TEXT(self.board)
        title_block.SetLayer(self.config_layer)

        if hasattr(pcbnew, 'GR_TEXT_HJUSTIFY_LEFT'):
            title_block.SetHorizJustify(pcbnew.GR_TEXT_HJUSTIFY_LEFT)
        elif hasattr(pcbnew, 'GR_TEXT_H_ALIGN_LEFT'):
            title_block.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)

        if hasattr(pcbnew, 'GR_TEXT_VJUSTIFY_TOP'):
            title_block.SetVertJustify(pcbnew.GR_TEXT_VJUSTIFY_TOP)
        elif hasattr(pcbnew, 'GR_TEXT_V_ALIGN_TOP'):
            title_block.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_TOP)

        title_block.SetVisible(False)
        self.config_textbox = title_block
        self.board.Add(title_block)
        self.CommitAdd(commit, title_block)

    def SaveConfig(self, zone_name, commit=None):
        if not isinstance(self.config, dict):
            self.config = {}
        self.config[__plugin_name__] = __version__
        self.config[zone_name] = self.BuildZoneConfig()
        self.config[__global_settings_key__] = self.BuildLastUsedConfig()
        self.EnsureConfigTextbox(commit=commit)
        self.CommitModify(commit, self.config_textbox)
        self.config_textbox.SetText(json.dumps(self.config, indent=2))

    def SaveLastUsedConfig(self, commit=None):
        if not isinstance(self.config, dict):
            self.config = {}
        self.config[__plugin_name__] = __version__
        self.config[__global_settings_key__] = self.BuildLastUsedConfig()
        self.EnsureConfigTextbox(commit=commit)
        self.CommitModify(commit, self.config_textbox)
        self.config_textbox.SetText(json.dumps(self.config, indent=2))

    def GetZoneConfigEntries(self):
        if not isinstance(self.config, dict):
            return {}
        entries = {}
        for key, value in self.config.items():
            if key in (__plugin_name__, __global_settings_key__):
                continue
            if isinstance(value, dict):
                entries[key] = value
        return entries


    def GetOverlappingItems(self):
        """Collect overlapping items.
            Every bounding box of any item found is a candidate to be inspected for overlapping.
        """

        area_bbox = self.area.GetBoundingBox()
        self.target_layers = self.GetZoneLayers(self.area)
        if not self.target_layers:
            self.target_layers = set(_layer_sequence(self.area.GetLayerSet()))

        if hasattr(self.board, 'GetModules'):
            modules = self.board.GetModules()
        else:
            modules = self.board.GetFootprints()

        tracks = self.board.GetTracks()

        self.overlappings = []

        for zone in _iter_zones(self.board):
            if zone is self.area:
                continue
            if not zone.GetBoundingBox().Intersects(area_bbox):
                continue
            if not self.IsOnTargetLayers(zone):
                continue
            zone_net = _item_netname(zone)
            zone_is_keepout = hasattr(zone, "GetDoNotAllowCopperPour") and zone.GetDoNotAllowCopperPour()
            if zone_net == self.net and not zone_is_keepout:
                continue
            self.overlappings.append(zone)

        for item in tracks:
            if not item.GetBoundingBox().Intersects(area_bbox):
                continue
            if not self.IsOnTargetLayers(item):
                continue
            if _is_pcb_via(item) or _item_type_name(item) in ['PCB_TRACK', 'PCB_ARC']:
                self.overlappings.append(item)

        for item in modules:
            if item.GetBoundingBox().Intersects(area_bbox):
                for pad in item.Pads():
                    if self.IsOnTargetLayers(pad):
                        self.overlappings.append(pad)
                if hasattr(item, "Zones"):
                    for zone in item.Zones():
                        zone_net = _item_netname(zone)
                        if self.IsOnTargetLayers(zone) and zone_net != self.net:
                            self.overlappings.append(zone)

    def FindSelectedValidZone(self):
        for area in _iter_zones(self.board):
            if area.IsSelected():
                if not area.IsOnCopperLayer():
                    continue
                if area.GetDoNotAllowCopperPour():
                    continue
                return area

        group_zone = self.GetSelectedStitchZoneFromGroup()
        if group_zone is not None:
            if not group_zone.IsOnCopperLayer():
                return None
            if group_zone.GetDoNotAllowCopperPour():
                return None
            return group_zone
        return None

    def SelectionSignature(self):
        zone_name = self.area.GetZoneName() if self.area is not None else ""
        net_name = self.net if self.net else ""
        return f"{zone_name}|{net_name}"

    def SetDisplayedNet(self, net_name):
        net_name = net_name or ""
        if not hasattr(self, "m_cbNet") or self.m_cbNet is None:
            return

        if not net_name:
            self.m_cbNet.SetValue("")
            return

        index = self.m_cbNet.FindString(net_name)
        if index != wx.NOT_FOUND:
            self.m_cbNet.Select(index)
        else:
            self.m_cbNet.SetValue(net_name)

    def GetDisplayedNet(self):
        if not hasattr(self, "m_cbNet") or self.m_cbNet is None:
            return ""
        value = ""
        try:
            value = self.m_cbNet.GetStringSelection()
        except Exception:
            value = ""
        if not value:
            try:
                value = self.m_cbNet.GetValue()
            except Exception:
                value = ""
        return value.strip()

    def RefreshSelectionContext(self):
        previous_signature = self.SelectionSignature()
        previous_zone_name = self.area.GetZoneName() if self.area is not None else ""

        zone = self.FindSelectedValidZone()
        if zone is None:
            self.area = None
            self.net = None
            self.viagroupname = None
            self.pcb_group = None
            self.owned_via_ids = set()
            self.SetDisplayedNet("")
            self.has_valid_selection = False
        else:
            self.area = zone
            self.net = zone.GetNetname()
            self.viagroupname = __viagroupname_base__ + zone.GetZoneName()
            self.pcb_group = self.FindGroupByName(self.viagroupname)
            if zone.GetZoneName() != previous_zone_name:
                self.LoadOwnedViasForZone(zone)
            self.SetDisplayedNet(self.net)
            self.has_valid_selection = bool(self.net)

        new_signature = self.SelectionSignature()
        changed = new_signature != previous_signature
        if changed:
            _debug_log(
                f"Selection changed: old={previous_signature or '<none>'} "
                f"new={new_signature or '<none>'}"
            )
        return changed

    def onSelectionPoll(self, event):
        if getattr(self, "_action_in_progress", False):
            return
        changed = self.RefreshSelectionContext()
        if changed:
            self.UpdateActionButtons(refresh_orphan_scan=False)
        elif self._last_selection_signature is None:
            self.UpdateActionButtons(refresh_orphan_scan=False)

        self._last_selection_signature = self.SelectionSignature()

    def BeginActionContext(self):
        _debug_log("BeginActionContext: freezing selection polling")
        self._action_in_progress = True
        self._selection_timer_was_running = False
        try:
            if hasattr(self, "selection_timer") and self.selection_timer.IsRunning():
                self._selection_timer_was_running = True
                self.selection_timer.Stop()
        except Exception:
            self._selection_timer_was_running = False

    def EndActionContext(self):
        _debug_log("EndActionContext: restoring selection polling")
        self._action_in_progress = False
        try:
            if getattr(self, "_selection_timer_was_running", False):
                self.selection_timer.Start(600)
        except Exception:
            pass
        self._selection_timer_was_running = False

    def ConfirmNetSelectionMismatch(self, action_name):
        displayed_net = self.GetDisplayedNet()
        zone = self.FindSelectedValidZone()
        selected_net = ""
        zone_name = ""
        if zone is not None:
            try:
                selected_net = zone.GetNetname() or ""
            except Exception:
                selected_net = ""
            try:
                zone_name = zone.GetZoneName() or ""
            except Exception:
                zone_name = ""

        if not displayed_net or not selected_net or displayed_net == selected_net:
            return True

        warning = _(
            u"You are about to %s with mismatched context.\n\n"
            u"Dialog net: %s\n"
            u"Currently selected zone net: %s\n"
            u"Selected zone name: %s\n\n"
            u"Continue anyway?"
        ) % (action_name, displayed_net, selected_net, zone_name if zone_name else _(u"(unnamed zone)"))
        _debug_log(
            f"Net mismatch warning before {action_name}: dialog_net={displayed_net} "
            f"selected_net={selected_net} zone={zone_name if zone_name else '<unnamed>'}"
        )
        return wx.MessageBox(
            warning,
            _(u"Confirm Net Mismatch"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self
        ) == wx.YES

    def GetAreaConfig(self):
        """Check selected area (if any) and verify if it is a valid container for vias.

        Returns:
            bool: Returns True if an area/zone is selected and matches the implant criteria, False otherwise.
        """

        changed = self.RefreshSelectionContext()
        if changed:
            self._last_selection_signature = self.SelectionSignature()
        if self.area is not None:
            _debug_log(f"GetAreaConfig: selected zone found net={self.net if self.net else '<none>'}")
            return True

        _debug_log("GetAreaConfig: no valid selected zone/group")
        return False

    def PopulateNets(self):
        """Populate nets widget."""

        self.m_cbNet.Clear()
        nets = self.board.GetNetsByName()

        # Tricky loop, the iterator should return two values, unluckly I'm not able to use the
        # first value of the couple so I'm recycling it as netname.
        for netname, net in nets.items():
            netname = net.GetNetname()
            if (netname != None) and (netname != ""):
                self.m_cbNet.Append(netname)

        # Select the net used by area (if any)
        self.SetDisplayedNet(self.net if self.net is not None else "")

    def ClearArea(self, show_message=True, commit=None, push_commit=True, include_user_vias=False):
        """Clear selected area."""

        _debug_log(f"ClearArea: start include_user_vias={include_user_vias}")
        if commit is None:
            commit = self.RequireUndoBackend("ClearArea", show_popup=show_message)
        if commit is None:
            return False
        self.RefreshOwnedViasState()
        self.ClearEditorSelection()
        to_remove = []
        removed_ids = set()
        netcode = self.board.GetNetcodeFromNetname(self.net) if self.net else -1

        for item in list(self.board.GetTracks()):
            if _is_pcb_via(item):
                via_uuid = _item_uuid(item)
                is_owned = bool(via_uuid and via_uuid in self.owned_via_ids)
                if is_owned:
                    to_remove.append(item)
                    removed_ids.add(via_uuid)
                    continue

                if not include_user_vias or netcode < 0:
                    continue
                try:
                    if item.GetNetCode() != netcode:
                        continue
                except Exception:
                    continue
                if self.IsInsideSelectedZone(item.GetPosition()):
                    to_remove.append(item)
                    if via_uuid:
                        removed_ids.add(via_uuid)
                # commit.Remove(item)

        for via in to_remove:
            self.SafeRemoveViaWithCommit(via, commit)
        self.ClearEditorSelection()

        viacount = len(to_remove)

        if removed_ids:
            self.owned_via_ids -= removed_ids

        if viacount > 0 and push_commit:
            self.CommitPush(commit, "ViaStitching: Clear")
        if viacount > 0:
            pcbnew.Refresh()
        _debug_log(f"ClearArea: done removed={viacount} include_user_vias={include_user_vias}")
        self.UpdateActionButtons()
        return viacount > 0

    def CheckClearance(self, via, area, edge_margin):
        """Check if via center keeps the requested margin from selected zone boundaries.

        Parameters:
            via (pcbnew.PCB_VIA): Via candidate
            area (pcbnew.ZONE_CONTAINER): Unused, kept for compatibility
            edge_margin (int): Required minimum margin from boundaries

        Returns:
            bool: True if via center satisfies edge margin, False otherwise.
        """
        return self.IsPointInsideZoneWithMargin(via.GetPosition(), edge_margin)

    def CheckOverlap(self, via):
        """Check if via overlaps or interfere with other items on the board.

        Parameters:
            via (pcbnew.VIA): Via to be checked

        Returns:
            bool: True if via overlaps with an item, False otherwise.
        """

        for item in self.overlappings:
            if not self.IsOnTargetLayers(item):
                continue

            if _is_pcb_pad(item):
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    return True
            elif _is_pcb_via(item):
                # For vias, enforce radial copper-edge spacing using center distance.
                # Candidate via is already inflated by pad_margin during overlap check.
                try:
                    center = via.GetPosition()
                    other = item.GetPosition()
                    dx = float(center.x - other.x)
                    dy = float(center.y - other.y)
                    min_dist = (float(via.GetWidth()) + float(item.GetWidth())) / 2.0
                    if (dx * dx + dy * dy) <= (min_dist * min_dist):
                        return True
                    continue
                except Exception:
                    pass
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    return True
            elif type(item).__name__ in ['ZONE', 'FP_ZONE', 'PCB_ZONE', 'ZONE_CONTAINER', 'ZONE_PROXY']:
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    return True
            elif type(item).__name__ in ['PCB_TRACK', 'PCB_ARC']:
                if item.GetBoundingBox().Intersects(via.GetBoundingBox()):
                    if type(item).__name__ == 'PCB_ARC':
                        return True
                    width = item.GetWidth()
                    dist, _ = pnt2line(via.GetPosition(), item.GetStart(), item.GetEnd())
                    if dist <= (width / 2) + (via.GetWidth() / 2):
                        return True
        return False

    def RebuildSelectedZoneCopper(self):
        if self.area is None:
            _debug_log("RebuildSelectedZoneCopper: no selected area")
            return False

        if not hasattr(pcbnew, "ZONE_FILLER"):
            _debug_log("RebuildSelectedZoneCopper: pcbnew has no ZONE_FILLER")
            return False

        try:
            filler = pcbnew.ZONE_FILLER(self.board)
        except Exception:
            _debug_log("RebuildSelectedZoneCopper: failed to construct ZONE_FILLER")
            return False

        try:
            # Preferred: refill just the selected zone.
            filler.Fill([self.area])
            pcbnew.Refresh()
            _debug_log("RebuildSelectedZoneCopper: refilled selected zone")
            return True
        except Exception:
            pass

        try:
            # Fallback: refill all zones on the board.
            if hasattr(self.board, "Zones"):
                filler.Fill(self.board.Zones())
            else:
                filler.Fill(_iter_zones(self.board))
            pcbnew.Refresh()
            _debug_log("RebuildSelectedZoneCopper: refilled all board zones")
            return True
        except Exception:
            _debug_log("RebuildSelectedZoneCopper: failed in fallback refill")
            return False

    def PromptRebuildZoneCopper(self):
        title = _(u"Selected Zone Has No Filled Copper")
        message = _(
            u"No candidate points landed inside filled copper for the selected zone.\n\n"
            u"Try rebuilding copper for this zone now and retry stitching?"
        )
        return _prompt_yes_no_with_memory(
            self, title, message, __pref_key_rebuild_zone_copper__
        )

    def FillupArea(self, show_message=True, allow_refill_prompt=True, commit=None, push_commit=True):
        """Fills selected area with vias."""

        _debug_log("FillupArea: start")
        inputs = self.ParseAndValidateInputs()
        if inputs is None:
            _debug_log("FillupArea: aborted due to invalid inputs")
            return False

        drillsize = inputs["drillsize"]
        viasize = inputs["viasize"]
        step_x = int(inputs["step_x"])
        step_y = int(inputs["step_y"])
        offset_x = int(inputs["offset_x"])
        offset_y = int(inputs["offset_y"])
        edge_margin = inputs["edge_margin"]
        pad_margin = inputs["pad_margin"]
        self.randomize = self.m_chkRandomize.GetValue()
        self.include_other_layers = self.m_chkIncludeOtherLayers.GetValue()
        self.pad_margin = pad_margin
        bbox = self.area.GetBoundingBox()
        top = bbox.GetTop()
        bottom = bbox.GetBottom()
        right = bbox.GetRight()
        left = bbox.GetLeft()
        netname = self.net
        if not netname:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Selected zone has no net."), context="fill_no_net")
            return False
        netcode = self.board.GetNetcodeFromNetname(netname)
        if netcode < 0:
            _show_error_with_log(self, _(u"ViaStitching"), _(u"Selected net is not valid on this board."), context="fill_invalid_net")
            return False
        if commit is None:
            commit = self.RequireUndoBackend("FillupArea", show_popup=show_message)
        if commit is None:
            return False
        viacount = 0
        candidates = 0
        inside_zone = 0
        rejected_overlap = 0
        rejected_edge_margin = 0

        center_segments = self.m_chkCenterSegments.GetValue() if hasattr(self, "m_chkCenterSegments") else True
        maximize_vias = self.m_chkMaximizeVias.GetValue() if hasattr(self, "m_chkMaximizeVias") else False
        randomize_points = self.randomize and not maximize_vias
        required_edge_margin = (viasize / 2) + edge_margin
        probe_step = max(1, int(step_x / 10))

        def _phase_offsets(step, base, samples):
            if step <= 0:
                return [0]
            offsets = {int(base % step)}
            if samples > 1:
                for i in range(samples):
                    offsets.add(int((i * step) // samples))
            return sorted(offsets)

        def _inside_margin_xy(xp, yp):
            return self.IsPointInsideZoneWithMargin(self.ToBoardPoint(xp, yp), required_edge_margin)

        def _row_inside_intervals(yp):
            intervals = []
            run_start = None
            xprobe = left
            while xprobe <= right:
                inside = _inside_margin_xy(xprobe, yp)
                if inside:
                    if run_start is None:
                        run_start = xprobe
                elif run_start is not None:
                    intervals.append((run_start, xprobe - probe_step))
                    run_start = None
                xprobe += probe_step
            if run_start is not None:
                intervals.append((run_start, right))
            return intervals

        def _grid_count_in_interval(start_x, a, b):
            if b < a:
                return 0
            k0 = int(math.ceil((a - start_x) / float(step_x)))
            k1 = int(math.floor((b - start_x) / float(step_x)))
            return max(0, k1 - k0 + 1)

        def _build_row_positions(yp, phase_x):
            start_x = left + ((phase_x - left) % step_x)
            if not center_segments and not maximize_vias:
                row = []
                xv = start_x
                while xv <= right:
                    row.append(int(xv))
                    xv += step_x
                return row

            row = []
            for a, b in _row_inside_intervals(yp):
                if b < a:
                    continue
                if maximize_vias:
                    n = int(math.floor((b - a) / float(step_x))) + 1
                else:
                    n = _grid_count_in_interval(start_x, a, b)
                if n <= 0:
                    continue

                if center_segments:
                    span = b - a
                    first = a + 0.5 * (span - (n - 1) * step_x)
                    for i in range(n):
                        row.append(int(round(first + i * step_x)))
                else:
                    k0 = int(math.ceil((a - start_x) / float(step_x)))
                    xv = start_x + k0 * step_x
                    while xv <= b:
                        row.append(int(xv))
                        xv += step_x
            return sorted({x for x in row if left <= x <= right})

        def _run_phase(phase_x, phase_y, apply_changes=False):
            phase_viacount = 0
            phase_candidates = 0
            phase_inside = 0
            phase_rejected_overlap = 0
            phase_rejected_edge = 0

            yv = top + ((phase_y - top) % step_y)
            while yv <= bottom:
                for xv in _build_row_positions(yv, phase_x):
                    phase_candidates += 1
                    if randomize_points:
                        xp = xv + random.uniform(-1, 1) * step_x / 5
                        yp = yv + random.uniform(-1, 1) * step_y / 5
                    else:
                        xp = xv
                        yp = yv

                    p = self.ToBoardPoint(xp, yp)
                    if not self.IsPointInsideZoneWithMargin(p, required_edge_margin):
                        phase_rejected_edge += 1
                        continue

                    phase_inside += 1
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(p)
                    if hasattr(via, "SetViaType") and hasattr(pcbnew, "VIATYPE_THROUGH"):
                        via.SetViaType(pcbnew.VIATYPE_THROUGH)
                    if hasattr(via, "SetLayerPair"):
                        fcu = getattr(pcbnew, "F_Cu", None)
                        bcu = getattr(pcbnew, "B_Cu", None)
                        if fcu is not None and bcu is not None:
                            via.SetLayerPair(fcu, bcu)
                    elif hasattr(via, "SetLayerSet"):
                        via.SetLayerSet(layer_set)
                    via.SetNetCode(netcode)
                    via.SetDrill(drillsize + 2 * pad_margin)
                    via.SetWidth(viasize + 2 * pad_margin)

                    if self.CheckOverlap(via):
                        phase_rejected_overlap += 1
                        continue

                    if not apply_changes:
                        phase_viacount += 1
                        continue

                    if self.pcb_group is None:
                        self.EnsureCurrentZoneGroup(commit=commit)

                    via.SetWidth(viasize)
                    via.SetDrill(drillsize)
                    self.board.Add(via)
                    self.CommitAdd(commit, via)
                    if self.pcb_group is not None:
                        if commit is not None:
                            self.CommitModify(commit, self.pcb_group)
                        try:
                            self.pcb_group.AddItem(via)
                        except Exception:
                            pass
                    via_uuid = _item_uuid(via)
                    if via_uuid:
                        self.owned_via_ids.add(via_uuid)
                    phase_viacount += 1
                yv += step_y

            return {
                "inserted": phase_viacount,
                "candidates": phase_candidates,
                "inside_zone": phase_inside,
                "rejected_overlap": phase_rejected_overlap,
                "rejected_edge_margin": phase_rejected_edge,
            }

        # Cycle trough area bounding box checking and implanting vias
        layer_set = self.area.GetLayerSet()
        hit_test_layers = self.GetZoneHitTestLayers(self.area)
        if not hit_test_layers:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(u"Unable to detect selected zone copper layers."),
                context="fill_no_zone_layers"
            )
            return False

        best_phase_x = offset_x
        best_phase_y = offset_y
        if maximize_vias:
            x_phases = _phase_offsets(step_x, offset_x, 6 if not center_segments else 1)
            y_phases = _phase_offsets(step_y, offset_y, 8)
            best_score = None
            for phase_y in y_phases:
                for phase_x in x_phases:
                    trial = _run_phase(phase_x, phase_y, apply_changes=False)
                    score = (
                        trial["inserted"],
                        -(trial["rejected_overlap"] + trial["rejected_edge_margin"]),
                        -trial["rejected_edge_margin"],
                    )
                    if best_score is None or score > best_score:
                        best_score = score
                        best_phase_x = phase_x
                        best_phase_y = phase_y
            _debug_log(
                f"FillupArea maximize search: best_phase=({best_phase_x},{best_phase_y}) "
                f"score={best_score}"
            )

        applied = _run_phase(best_phase_x, best_phase_y, apply_changes=True)
        viacount = applied["inserted"]
        candidates = applied["candidates"]
        inside_zone = applied["inside_zone"]
        rejected_overlap = applied["rejected_overlap"]
        rejected_edge_margin = applied["rejected_edge_margin"]

        self.last_fill_stats = {
            "inserted": viacount,
            "candidates": candidates,
            "inside_zone": inside_zone,
            "rejected_overlap": rejected_overlap,
            "rejected_edge_margin": rejected_edge_margin,
            "pruned_stale_vias": self.pruned_stale_vias,
        }

        if viacount > 0 and push_commit:
            self.CommitPush(commit, "ViaStitching: Fill")
        if viacount > 0:
            pcbnew.Refresh()
        elif show_message:
            layer_names = []
            if hasattr(self.board, "GetLayerName"):
                for layer in hit_test_layers:
                    try:
                        lname = self.board.GetLayerName(layer)
                    except Exception:
                        lname = str(layer)
                    if lname and lname.lower() != "undefined":
                        layer_names.append(lname)
            if not layer_names:
                layer_names = [str(layer) for layer in hit_test_layers]
            layer_name = ", ".join(layer_names)
            details = [
                _(u"No vias implanted."),
                _(u"Candidate points tested: %d") % candidates,
                _(u"Points inside selected zone (%s): %d") % (layer_name, inside_zone),
                _(u"Rejected by overlap/pad-margin checks: %d") % rejected_overlap,
                _(u"Rejected by edge margin checks: %d") % rejected_edge_margin,
            ]
            if self.pruned_stale_vias > 0:
                details.append(_(u"Removed stale plugin vias outside zone: %d") % self.pruned_stale_vias)

            if inside_zone == 0:
                if allow_refill_prompt and self.PromptRebuildZoneCopper():
                    if self.RebuildSelectedZoneCopper():
                        return self.FillupArea(show_message=show_message,
                                               allow_refill_prompt=False,
                                               commit=commit,
                                               push_commit=push_commit)
                    _show_error_with_log(
                        self,
                        _(u"Copper Rebuild Failed"),
                        _(u"Unable to rebuild zone copper automatically. Please run KiCad copper refill and retry."),
                        context="fill_rebuild_failed"
                    )
                    self.UpdateActionButtons()
                    return False
                details.append(_(u"No candidate points landed inside filled zone copper. Refill the zone and/or adjust spacing/offset."))
            elif rejected_overlap == inside_zone:
                details.append(_(u"All in-zone points were rejected by overlap/pad-margin checks. Reduce pad margin or spacing if needed."))
                if not self.include_other_layers:
                    details.append(_(u"Tip: this run only checked overlaps on the selected zone layer (toggle is OFF)."))
                else:
                    details.append(_(u"Tip: disable \"Check overlaps on all copper layers\" to only check the selected zone layer."))
            elif rejected_edge_margin == inside_zone:
                details.append(_(u"All in-zone points were rejected by edge margin. Reduce edge margin or spacing."))

            wx.MessageBox("\n".join(details))
        _debug_log(
            f"FillupArea: done inserted={viacount} candidates={candidates} inside={inside_zone} "
            f"rejected_overlap={rejected_overlap} rejected_edge={rejected_edge_margin} "
            f"pruned_stale={self.pruned_stale_vias}"
        )
        self.UpdateActionButtons()
        return viacount > 0

    def EnsureCurrentZoneGroup(self, commit=None):
        self.pcb_group = None
        for group in self.GetGroups():
            if group.GetName() == self.viagroupname:
                self.pcb_group = group
                break

        if self.pcb_group is None:
            self.pcb_group = pcbnew.PCB_GROUP(None)
            self.pcb_group.SetName(self.viagroupname)
            self.board.Add(self.pcb_group)
            if commit is not None:
                self.CommitAdd(commit, self.pcb_group)
            else:
                _debug_log("EnsureCurrentZoneGroup: created group without commit backend")
            _debug_log(f"EnsureCurrentZoneGroup: created group {self.viagroupname}")
        self.EnsureZoneInGroup(commit=commit)

    def RestitchCurrentZone(self, show_message=False, include_user_vias=False, commit=None, push_commit=False):
        if commit is None:
            commit = self.RequireUndoBackend("RestitchCurrentZone", show_popup=show_message)
        if commit is None:
            return False
        _debug_log(f"RestitchCurrentZone: start include_user_vias={include_user_vias}")
        self.pruned_stale_vias = 0
        self.pruned_stale_vias = self.PruneGroupedViasOutsideZone(commit=commit)
        self.ClearArea(show_message=False,
                       commit=commit,
                       push_commit=False,
                       include_user_vias=include_user_vias)
        if commit is None:
            self.RemoveCurrentStitchGroup(commit=None, push_commit=False)
        self.GetOverlappingItems()
        filled = self.FillupArea(show_message=show_message, commit=commit, push_commit=False)
        if filled and push_commit:
            self.CommitPush(commit, "ViaStitching: Update Array")
        _debug_log(f"RestitchCurrentZone: done filled={filled} pruned_stale={self.pruned_stale_vias}")
        return filled

    def onProcessAction(self, event):
        """Manage main button (Ok) click event."""
        if not self.IsSelectionValid():
            _debug_log("onProcessAction: ignored because selection is not valid")
            self.UpdateActionButtons()
            return
        if not self.ConfirmNetSelectionMismatch(_(u"place/update via array")):
            _debug_log("onProcessAction: canceled by net mismatch warning")
            return
        _debug_log("onProcessAction: start")
        self.BeginActionContext()

        try:
            zone_name = self.area.GetZoneName()
            created_zone_name = False
            if zone_name == "":
                for i in range(1000):
                    candidate_name = f"stitch_zone_{i}"
                    if candidate_name not in self.config.keys():
                        zone_name = candidate_name
                        break
                else:
                    wx.LogError("Tried 1000 different names and all were taken. Please give a name to the zone.")
                    self.Destroy()
                    return
                created_zone_name = True
                self.viagroupname = __viagroupname_base__ + zone_name

            commit = self.RequireUndoBackend("onProcessAction")
            if commit is None:
                return

            self.include_other_layers = self.m_chkIncludeOtherLayers.GetValue()
            self.ClearEditorSelection()

            include_user_vias = False
            user_vias = self.CountUserNetViasInZone()
            if user_vias > 0:
                include_user_vias = self.PromptReplaceUserNetVias(user_vias)

            if self.RestitchCurrentZone(show_message=True,
                                        include_user_vias=include_user_vias,
                                        commit=commit,
                                        push_commit=False):
                if created_zone_name:
                    self.CommitModify(commit, self.area)
                    self.area.SetZoneName(zone_name)
                self.SaveConfig(zone_name, commit=commit)
                self.CommitPush(commit, "ViaStitching: Update Array")
                _debug_log("onProcessAction: success")
                self.CloseDialog(wx.ID_OK)
            else:
                _debug_log("onProcessAction: no vias placed")
        finally:
            self.EndActionContext()

    def onClearAction(self, event):
        """Manage clear vias button (Clear) click event."""
        _debug_log("onClearAction: start")

        self.UpdateActionButtons()
        if not self.m_btnClear.IsEnabled():
            self.UpdateActionButtons()
            _debug_log("onClearAction: ignored because button disabled")
            return
        if not self.ConfirmNetSelectionMismatch(_(u"remove via array")):
            _debug_log("onClearAction: canceled by net mismatch warning")
            return
        self.BeginActionContext()

        try:
            include_user_vias = False
            user_vias = self.CountUserNetViasInZone()
            if user_vias > 0:
                include_user_vias = self.PromptRemoveUserNetVias(user_vias)

            commit = self.RequireUndoBackend("onClearAction")
            if commit is None:
                return
            if self.ClearArea(show_message=False, commit=commit, push_commit=False, include_user_vias=include_user_vias):
                zone_name = self.area.GetZoneName()
                if zone_name:
                    self.SaveConfig(zone_name, commit=commit)
                else:
                    self.SaveLastUsedConfig(commit=commit)
                if self.CountExistingOwnedVias() == 0:
                    self.RemoveCurrentStitchGroup(commit=commit, push_commit=False)
                self.CommitPush(commit, "ViaStitching: Remove Array")
                self.UpdateActionButtons()
                _debug_log("onClearAction: success")
                self.CloseDialog(wx.ID_OK)
            else:
                _debug_log("onClearAction: no vias removed for current zone ownership set")
                _show_info(
                    self,
                    _(u"ViaStitching"),
                    _(u"No plugin-owned vias were found for the selected zone.")
                )
        finally:
            self.EndActionContext()

    def onCleanOrphansAction(self, event):
        _debug_log("onCleanOrphansAction: start")
        scan = self.ScanOrphanOwnedVias()
        orphan_vias = scan["orphan_vias"]
        orphan_ids = scan["orphan_ids"]
        missing_ids = scan["missing_ids"]
        counts_by_net = scan["counts_by_net"]

        if not orphan_vias and not missing_ids:
            _show_info(self, _(u"ViaStitching"), _(u"No orphan plugin vias were found."))
            _debug_log("onCleanOrphansAction: nothing to clean")
            self.UpdateActionButtons()
            return

        lines = [_(u"Remove orphan plugin vias outside their configured zones?"), u""]
        total_orphans = len(orphan_vias)
        if total_orphans > 0:
            lines.append(_(u"Orphan vias to remove: %d") % total_orphans)
            for net_name in sorted(counts_by_net.keys()):
                lines.append(_(u" - %s: %d") % (net_name, counts_by_net[net_name]))
        if missing_ids:
            lines.append(_(u"Stale config IDs to clean: %d") % len(missing_ids))

        should_remove = (wx.MessageBox(
            u"\n".join(lines),
            _(u"Clean Orphan Vias"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self
        ) == wx.YES)
        if not should_remove:
            _debug_log("onCleanOrphansAction: canceled by user")
            return

        commit = self.RequireUndoBackend("onCleanOrphansAction")
        if commit is None:
            return

        for via in orphan_vias:
            if commit is not None:
                self.SafeRemoveViaWithCommit(via, commit)
            else:
                self.SafeRemoveVia(via)

        config_changed = self.CleanupOwnedViaConfigIds(remove_ids=orphan_ids, missing_ids=missing_ids)
        if config_changed:
            self.SaveConfigBlob(commit=commit)

        if commit is not None and (orphan_vias or config_changed):
            self.CommitPush(commit, "ViaStitching: Clean Orphans")

        if orphan_vias:
            pcbnew.Refresh()

        _debug_log(
            f"onCleanOrphansAction: removed_orphans={len(orphan_vias)} "
            f"cleaned_missing_ids={len(missing_ids)} config_changed={config_changed}"
        )
        self.UpdateActionButtons()

    def onResetPromptChoices(self, event):
        cleared = _clear_user_prefs()
        if cleared:
            _show_info(self, _(u"ViaStitching"), _(u"Saved popup choices have been cleared."))
            _debug_log("onResetPromptChoices: cleared user prompt preferences")
        else:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(u"Unable to clear saved popup choices."),
                context="reset_prompt_choices"
            )

    def onToggleLogging(self, event):
        enabled = bool(self.m_chkDebugLogging.GetValue()) if hasattr(self, "m_chkDebugLogging") else True
        ok = _set_logging_enabled(enabled)
        if not ok:
            _show_error_with_log(
                self,
                _(u"ViaStitching"),
                _(u"Unable to save logging preference."),
                context="toggle_logging_save_pref"
            )
            return
        if enabled:
            _debug_log("Debug logging enabled from UI.")
        else:
            _debug_log_force("Debug logging disabled from UI.")

    def onCloseWindow(self, event):
        """Manage Close button click event."""
        _debug_log("onCloseWindow: closing dialog")
        self.CloseDialog(wx.ID_CANCEL)

    def onParentWindowClose(self, event):
        self.CloseDialog(wx.ID_CANCEL)
        event.Skip()

    def GetStandardLayerName(self, layerid):
        if hasattr(pcbnew, 'BOARD_GetStandardLayerName'):
            try:
                return pcbnew.BOARD_GetStandardLayerName(layerid)
            except Exception:
                pass
        if hasattr(self.board, 'GetStandardLayerName'):
            try:
                return self.board.GetStandardLayerName(layerid)
            except Exception:
                pass
        if hasattr(self.board, 'GetLayerName'):
            try:
                return self.board.GetLayerName(layerid)
            except Exception:
                return ""
        return ""

    def getConfigLayer(self):
        self.config_layer = 0
        user_layer = getattr(pcbnew, "User_9", None)
        if user_layer is None:
            user_layer = getattr(pcbnew, "Cmts_User", None)
        layer_start = getattr(pcbnew, "PCBNEW_LAYER_ID_START", 0)
        layer_count = getattr(pcbnew, "PCB_LAYER_ID_COUNT", 64)

        for i in range(layer_start, layer_start + layer_count):
            layer_name = self.GetStandardLayerName(i)
            if __plugin_config_layer_name__ == layer_name:
                self.config_layer = i
                return
            if user_layer is None and layer_name in ("User.9", "Cmts.User"):
                user_layer = i

        if user_layer is None:
            return

        self.config_layer = user_layer
        if hasattr(self.board, "SetLayerName"):
            try:
                self.board.SetLayerName(self.config_layer, __plugin_config_layer_name__)
            except Exception:
                pass


def _get_dialog_parent_window():
    try:
        active = wx.GetActiveWindow()
        if active is not None:
            return active
    except Exception:
        pass

    try:
        app = wx.GetApp()
        if app is not None and app.GetTopWindow() is not None:
            return app.GetTopWindow()
    except Exception:
        pass

    return None


def InitViaStitchingDialog(board):
    """Initalize dialog."""
    global _active_dialog
    _debug_log("InitViaStitchingDialog: invoked")

    if _active_dialog is not None:
        try:
            if _active_dialog.IsShown():
                _debug_log("InitViaStitchingDialog: reopening because existing dialog is already open")
                _active_dialog.CloseDialog(wx.ID_CANCEL)
        except Exception:
            pass
        _active_dialog = None

    parent = _get_dialog_parent_window()
    dlg = ViaStitchingDialog(board, parent=parent)
    if dlg is None:
        return None
    if not hasattr(dlg, "board") or dlg.board is None:
        return None
    _active_dialog = dlg
    dlg.Centre(wx.BOTH)
    dlg.Show(True)
    try:
        dlg.Raise()
    except Exception:
        pass
    _debug_log("InitViaStitchingDialog: dialog shown modeless and raised to front")
    return dlg


class aVector():

    def __init__(self, point):
        if hasattr(point, "x") and hasattr(point, "y"):
            self.x = float(point.x)
            self.y = float(point.y)
        elif isinstance(point, (list, tuple)):
            self.x = point[0]
            self.y = point[1]
        else:
            raise TypeError("Unsupported point type")

    def __sub__(self, other):
        return aVector([self.x - float(other.x), self.y - float(other.y)])

    def __mul__(self, other):
        return aVector([self.x * float(other), self.y * float(other)])

    def __add__(self, other):
        return aVector([self.x + float(other.x), self.y + float(other.y)])

    def __truediv__(self, other):
        return aVector([self.x / other, self.y / other])

    @staticmethod
    def norm(vector):
        return sqrt(pow(vector.x, 2) + pow(vector.y, 2))

    @staticmethod
    def dot(vector1, vector2):
        return vector1.x * vector2.x + vector1.y * vector2.y


# Given a line with coordinates 'start' and 'end' and the
# coordinates of a point 'point' the proc returns the shortest
# distance from pnt to the line and the coordinates of the
# nearest point on the line.
#
# 1  Convert the line segment to a vector ('line_vec').
# 2  Create a vector connecting start to pnt ('pnt_vec').
# 3  Find the length of the line vector ('line_len').
# 4  Convert line_vec to a unit vector ('line_unitvec').
# 5  Scale pnt_vec by line_len ('pnt_vec_scaled').
# 6  Get the dot product of line_unitvec and pnt_vec_scaled ('t').
# 7  Ensure t is in the range 0 to 1.
# 8  Use t to get the nearest location on the line to the end
#    of vector pnt_vec_scaled ('nearest').
# 9  Calculate the distance from nearest to pnt_vec_scaled.
# 10 Translate nearest back to the start/end line.
# Malcolm Kesson 16 Dec 2012

def pnt2line(point, start, end):
    pnt = vector([point.x, point.y])
    strt = vector([start.x, start.y])
    nd = vector([end.x, end.y])
    line_vec = nd - strt
    pnt_vec = pnt - strt
    line_len = norm(line_vec)
    if line_len == 0:
        return norm(pnt_vec), strt
    line_unitvec = line_vec / line_len
    pnt_vec_scaled = pnt_vec / line_len
    t = dot(line_unitvec, pnt_vec_scaled)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    nearest = line_vec * t
    dist = norm(pnt_vec - nearest)
    nearest = nearest + strt
    return dist, nearest


norm = aVector.norm
vector = aVector
dot = aVector.dot
if numpy_available:
    norm = np.linalg.norm
    vector = np.array
    dot = np.dot
