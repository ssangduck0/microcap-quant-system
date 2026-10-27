import sys; sys.path.insert(0, __import__("os").environ["QS_ROOT"])
import ui_kit, report_dialog
ui_kit.inject()
report_dialog.render("HUBC")
