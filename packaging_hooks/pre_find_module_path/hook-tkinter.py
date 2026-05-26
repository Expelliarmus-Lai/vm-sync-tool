"""Keep tkinter discoverable when local Tcl/Tk probing is too conservative."""


def pre_find_module_path(_hook_api):
    return
