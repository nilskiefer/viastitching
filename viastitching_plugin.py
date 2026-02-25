#!/usr/bin/env python

# ViaStitching for pcbnew
# This is the action plugin interface
# (c) Michele Santucci 2019
#

import os
import gettext

import wx
import pcbnew
from pcbnew import ActionPlugin

_ = gettext.gettext

class ViaStitchingPlugin(ActionPlugin):
    def defaults(self):
        self.name = _(u"ViaStitching")
        self.category = _(u"Modify PCB")
        self.description = _(u"Fill selected copper zone with stitching vias.")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'viastitching.png')

    def Run(self):
        try:
            from .viastitching_dialog import InitViaStitchingDialog
            InitViaStitchingDialog(pcbnew.GetBoard())
        except Exception as exc:
            wx.MessageBox(
                _(u"Failed to open ViaStitching dialog:\n%s") % str(exc),
                _(u"ViaStitching"),
                wx.OK | wx.ICON_ERROR,
            )
