# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 3.10.1-0-g8feb16b3)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc

import gettext
_ = gettext.gettext

###########################################################################
## Class viastitching_gui
###########################################################################

class viastitching_gui ( wx.Dialog ):

	def __init__( self, parent ):
		wx.Dialog.__init__ ( self, parent, id = wx.ID_ANY, title = _(u"Via Stitching"), pos = wx.DefaultPosition, size = wx.Size( -1,-1 ), style = wx.DEFAULT_DIALOG_STYLE )

		self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )

		bMainSizer = wx.BoxSizer( wx.VERTICAL )

		bHSizer1 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_lblNetName = wx.StaticText( self, wx.ID_ANY, _(u"Net name"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblNetName.Wrap( -1 )

		bHSizer1.Add( self.m_lblNetName, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT|wx.ALL, 5 )

		m_cbNetChoices = []
		self.m_cbNet = wx.ComboBox( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, m_cbNetChoices, wx.CB_DROPDOWN|wx.CB_READONLY|wx.CB_SORT )
		self.m_cbNet.SetMinSize( wx.Size( 360,-1 ) )
		bHSizer1.Add( self.m_cbNet, 1, wx.ALL|wx.EXPAND, 5 )


		bMainSizer.Add( bHSizer1, 1, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.EXPAND, 5 )

		bHSizer2 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_lblVia = wx.StaticText( self, wx.ID_ANY, _(u"Size / drill"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblVia.Wrap( -1 )

		bHSizer2.Add( self.m_lblVia, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtViaSize = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtViaSize.SetMinSize( wx.Size( 120,-1 ) )		
		bHSizer2.Add( self.m_txtViaSize, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtViaDrillSize = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtViaDrillSize.SetMinSize( wx.Size( 120,-1 ) )
		bHSizer2.Add( self.m_txtViaDrillSize, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_lblUnit1 = wx.StaticText( self, wx.ID_ANY, _(u"mm"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblUnit1.Wrap( -1 )

		bHSizer2.Add( self.m_lblUnit1, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


		bMainSizer.Add( bHSizer2, 1, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.EXPAND, 5 )

		bHSizer3 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_lblSpacing = wx.StaticText( self, wx.ID_ANY, _(u"Spacing (V/H)"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblSpacing.Wrap( -1 )

		bHSizer3.Add( self.m_lblSpacing, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtVSpacing = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtVSpacing.SetMinSize( wx.Size( 120,-1 ) )		
		bHSizer3.Add( self.m_txtVSpacing, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtHSpacing = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtHSpacing.SetMinSize( wx.Size( 120,-1 ) )		
		bHSizer3.Add( self.m_txtHSpacing, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_lblUnit2 = wx.StaticText( self, wx.ID_ANY, _(u"mm"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblUnit2.Wrap( -1 )

		bHSizer3.Add( self.m_lblUnit2, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


		bMainSizer.Add( bHSizer3, 1, wx.EXPAND, 5 )

		bHSizer6 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_lblOffset = wx.StaticText( self, wx.ID_ANY, _(u"Offset (V/H)"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblOffset.Wrap( -1 )

		bHSizer6.Add( self.m_lblOffset, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtVOffset = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtVOffset.SetMinSize( wx.Size( 120,-1 ) )		
		bHSizer6.Add( self.m_txtVOffset, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtHOffset = wx.TextCtrl( self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtHOffset.SetMinSize( wx.Size( 120,-1 ) )		
		bHSizer6.Add( self.m_txtHOffset, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_lblUnit3 = wx.StaticText( self, wx.ID_ANY, _(u"mm"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblUnit3.Wrap( -1 )

		bHSizer6.Add( self.m_lblUnit3, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


		bMainSizer.Add( bHSizer6, 1, wx.EXPAND, 5 )

		bSizer7 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_staticText6 = wx.StaticText( self, wx.ID_ANY, _(u"Edge margin"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_staticText6.Wrap( -1 )

		bSizer7.Add( self.m_staticText6, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtClearance = wx.TextCtrl( self, wx.ID_ANY, _(u"0"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtClearance.SetMinSize( wx.Size( 120,-1 ) )		
		bSizer7.Add( self.m_txtClearance, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_lblUnit4 = wx.StaticText( self, wx.ID_ANY, _(u"mm"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblUnit4.Wrap( -1 )
		bSizer7.Add( self.m_lblUnit4, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


		bMainSizer.Add( bSizer7, 1, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.EXPAND, 5 )

		bSizer8 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_staticTextPadMargin = wx.StaticText( self, wx.ID_ANY, _(u"Pad margin"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_staticTextPadMargin.Wrap( -1 )
		bSizer8.Add( self.m_staticTextPadMargin, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_txtPadMargin = wx.TextCtrl( self, wx.ID_ANY, _(u"0"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_txtPadMargin.SetMinSize( wx.Size( 120,-1 ) )
		bSizer8.Add( self.m_txtPadMargin, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_lblUnit5 = wx.StaticText( self, wx.ID_ANY, _(u"mm"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblUnit5.Wrap( -1 )
		bSizer8.Add( self.m_lblUnit5, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		bMainSizer.Add( bSizer8, 1, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL|wx.EXPAND, 5 )

		bOptionsRow = wx.BoxSizer( wx.HORIZONTAL )

		bLeftOptions = wx.BoxSizer( wx.VERTICAL )

		self.m_chkClearOwn = wx.CheckBox( self, wx.ID_ANY, _(u"Clear only plugin placed vias"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_chkClearOwn.SetValue(True)
		bLeftOptions.Add( self.m_chkClearOwn, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_chkMaximizeVias = wx.CheckBox( self, wx.ID_ANY, _(u"Try to maximize vias"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_chkMaximizeVias.SetValue(False)
		bLeftOptions.Add( self.m_chkMaximizeVias, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_chkCenterSegments = wx.CheckBox( self, wx.ID_ANY, _(u"Center local segments"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_chkCenterSegments.SetValue(True)
		bLeftOptions.Add( self.m_chkCenterSegments, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_chkIncludeOtherLayers = wx.CheckBox( self, wx.ID_ANY, _(u"Check overlaps on all copper layers (safer, slower)"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_chkIncludeOtherLayers.SetValue(True)
		bLeftOptions.Add( self.m_chkIncludeOtherLayers, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_chkRandomize = wx.CheckBox( self, wx.ID_ANY, _(u"Randomize"), wx.DefaultPosition, wx.DefaultSize, 0 )
		bLeftOptions.Add( self.m_chkRandomize, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_chkDebugLogging = wx.CheckBox( self, wx.ID_ANY, _(u"Enable logging"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_chkDebugLogging.SetValue(True)
		bLeftOptions.Add( self.m_chkDebugLogging, 0, wx.ALIGN_LEFT|wx.ALL, 2 )

		self.m_btnCleanOrphans = wx.Button( self, wx.ID_ANY, _(u"Clean &Orphan Vias"), wx.DefaultPosition, wx.DefaultSize, 0 )
		bLeftOptions.Add( self.m_btnCleanOrphans, 0, wx.ALIGN_LEFT|wx.TOP|wx.BOTTOM, 8 )

		self.m_btnResetPrompts = wx.Button( self, wx.ID_ANY, _(u"Reset Prompt &Choices"), wx.DefaultPosition, wx.DefaultSize, 0 )
		bLeftOptions.Add( self.m_btnResetPrompts, 0, wx.ALIGN_LEFT|wx.BOTTOM, 2 )

		bOptionsRow.Add( bLeftOptions, 0, wx.ALL|wx.EXPAND, 5 )

		bRightPreview = wx.BoxSizer( wx.VERTICAL )

		self.m_lblPreview = wx.StaticText( self, wx.ID_ANY, _(u"Placement Preview"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblPreview.Wrap( -1 )

		bRightPreview.Add( self.m_lblPreview, 0, wx.ALL, 2 )

		self.m_previewPanel = wx.Panel( self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.BORDER_SIMPLE|wx.TAB_TRAVERSAL )
		self.m_previewPanel.SetMinSize( wx.Size( 420,260 ) )
		bRightPreview.Add( self.m_previewPanel, 1, wx.EXPAND|wx.ALL, 2 )

		self.m_lblPreviewLegend = wx.StaticText( self, wx.ID_ANY, _(u"Green: accepted  Orange: overlap reject  Red: edge reject"), wx.DefaultPosition, wx.DefaultSize, 0 )
		self.m_lblPreviewLegend.Wrap( -1 )

		bRightPreview.Add( self.m_lblPreviewLegend, 0, wx.ALL, 2 )

		bOptionsRow.Add( bRightPreview, 1, wx.EXPAND|wx.LEFT, 8 )

		bMainSizer.Add( bOptionsRow, 0, wx.EXPAND, 5 )

		bHSizer5 = wx.BoxSizer( wx.HORIZONTAL )

		self.m_btnCancel = wx.Button( self, wx.ID_ANY, _(u"&Cancel"), wx.DefaultPosition, wx.DefaultSize, 0 )
		bHSizer5.Add( self.m_btnCancel, 0, wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )

		self.m_btnClear = wx.Button( self, wx.ID_ANY, _(u"Remove &Via Array"), wx.DefaultPosition, wx.DefaultSize, 0 )
		bHSizer5.Add( self.m_btnClear, 0, wx.ALL, 5 )

		self.m_btnOk = wx.Button( self, wx.ID_ANY, _(u"&Ok"), wx.DefaultPosition, wx.DefaultSize, 0 )

		self.m_btnOk.SetDefault()
		bHSizer5.Add( self.m_btnOk, 0, wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5 )


		bMainSizer.Add( bHSizer5, 0, wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL, 5 )


		self.SetSizer( bMainSizer )
		self.Layout()
		bMainSizer.Fit( self )

		self.Centre( wx.BOTH )

	def __del__( self ):
		pass
