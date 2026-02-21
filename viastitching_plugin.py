#!/usr/bin/env python

# ViaStitching for pcbnew
# This is the action plugin interface
# (c) Michele Santucci 2019
#

import os
import gettext

import wx
from pcbnew import ActionPlugin

_ = gettext.gettext

class ViaStitchingPlugin(ActionPlugin):
    def defaults(self):
        self.name = _(u"ViaStitching")
        self.category = _(u"Modify PCB")
        self.description = _(u"IPC-only: use KiCad 9 IPC ViaStitching actions for transactional undo/redo")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'viastitching.png')

    def Run(self):
        wx.MessageBox(
            _(
                u"This legacy ActionPlugin path is disabled.\n\n"
                u"Your KiCad build does not expose BOARD_COMMIT in pcbnew Python, so proper undo/redo "
                u"cannot be guaranteed here.\n\n"
                u"Use the KiCad 9 IPC actions instead:\n"
                u" - Update Via Array\n"
                u" - Update Via Array (Maximize)\n"
                u" - Remove Via Array\n"
                u" - Clean Orphan Vias\n\n"
                u"Also enable: Preferences -> Plugins -> Enable KiCad API"
            ),
            _(u"ViaStitching"),
            wx.OK | wx.ICON_INFORMATION
        )
