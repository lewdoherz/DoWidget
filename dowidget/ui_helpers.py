"""Shared plain-text native widgets; never interpret upstream labels as HTML."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def label(text, name="", wrap=True):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    result.setObjectName(name)
    return result


def metric_text(metric):
    return f"{metric.currency} {metric.amount:f}" + (" minor units" if metric.unit == "minor" else "")
