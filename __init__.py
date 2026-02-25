import os
import traceback


def _error_log_path():
    return os.path.join(os.path.dirname(__file__), "viastitching_plugin_error.log")


try:
    from .viastitching_plugin import ViaStitchingPlugin

    ViaStitchingPlugin().register()
except Exception:
    err = traceback.format_exc()
    try:
        with open(_error_log_path(), "w", encoding="utf-8") as f:
            f.write(err)
    except Exception:
        pass

    import pcbnew
    import wx

    class ViaStitchingLoadErrorPlugin(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = "ViaStitching"
            self.category = "Modify PCB"
            self.description = "ViaStitching failed to load; open error log for details."

        def Run(self):
            wx.MessageBox(
                "ViaStitching failed to load.\n\n"
                f"See error log:\n{_error_log_path()}",
                "ViaStitching",
                wx.OK | wx.ICON_ERROR,
            )

    ViaStitchingLoadErrorPlugin().register()
