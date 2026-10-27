import sys; sys.path.insert(0, __import__("os").environ["QS_ROOT"])
import ui_kit, fundscan_ui
ui_kit.inject()
fundscan_ui.render_detail("SMSI", "$")
