import os
import streamlit.components.v1 as components

_component_func = components.declare_component(
    "draggable_table",
    path=os.path.dirname(os.path.abspath(__file__)),
)


def draggable_table(data: list, font_size: int = 13, key: str = None):
    """
    Render a drag-and-drop sortable table.

    Returns one of:
      {"type": "reorder", "order": [int, ...]}   — user finished a drag
      {"type": "show_desc", "key": "ISSUE-123"}  — user clicked the description button
      None                                        — no interaction yet
    """
    return _component_func(data=data, font_size=font_size, default=None, key=key)
