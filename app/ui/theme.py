"""Shared visual language for the ElectroCap desktop interface."""

from __future__ import annotations


APP_STYLESHEET = """
QMainWindow,
QWidget#appRoot,
QWidget#page {
    background-color: #F3F7F9;
    color: #18313B;
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
    font-size: 14px;
}

QLabel#pageTitle {
    color: #123B4A;
    font-size: 25px;
    font-weight: 700;
}

QLabel#brandFallback {
    color: #0F5E73;
    font-size: 44px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#supportingText {
    color: #5B727C;
    font-size: 14px;
}

QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #D8E4E8;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 650;
    margin-top: 14px;
    padding: 18px 14px 14px 14px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: #234D5C;
    background-color: #F3F7F9;
}

QLineEdit,
QSpinBox,
QDateEdit,
QComboBox,
QPlainTextEdit,
QTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #C8D8DE;
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: #1A7C91;
    selection-color: #FFFFFF;
}

QLineEdit:focus,
QSpinBox:focus,
QDateEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus {
    border: 2px solid #1A7C91;
    padding: 6px 8px;
}

QPushButton {
    min-height: 34px;
    padding: 5px 16px;
    border: 1px solid #BDD0D7;
    border-radius: 7px;
    background-color: #FFFFFF;
    color: #234D5C;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #EEF6F8;
    border-color: #8FB5C0;
}

QPushButton:pressed {
    background-color: #DFEDF1;
}

QPushButton:disabled {
    background-color: #E9EFF1;
    border-color: #D7E1E4;
    color: #94A5AC;
}

QPushButton#primaryButton,
QPushButton#heroPrimaryButton {
    background-color: #126E82;
    border-color: #126E82;
    color: #FFFFFF;
}

QPushButton#primaryButton:hover,
QPushButton#heroPrimaryButton:hover {
    background-color: #0D5D70;
    border-color: #0D5D70;
}

QPushButton#primaryButton:pressed,
QPushButton#heroPrimaryButton:pressed {
    background-color: #094B5B;
}

QPushButton#secondaryButton,
QPushButton#heroSecondaryButton {
    background-color: #E8F5F4;
    border-color: #9CCECB;
    color: #17645F;
}

QPushButton#secondaryButton:hover,
QPushButton#heroSecondaryButton:hover {
    background-color: #D9EFED;
    border-color: #70B5B0;
}

QPushButton#heroPrimaryButton,
QPushButton#heroSecondaryButton {
    min-width: 310px;
    min-height: 58px;
    font-size: 16px;
    border-radius: 10px;
}

QPushButton#navigationButton {
    background-color: transparent;
    border-color: transparent;
    color: #35616F;
    padding-left: 4px;
    padding-right: 10px;
}

QPushButton#navigationButton:hover {
    background-color: #E5F0F3;
}

QTableWidget,
QListWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F7FAFB;
    border: 1px solid #D8E4E8;
    border-radius: 8px;
    gridline-color: #E7EEF0;
    outline: 0;
}

QTableWidget::item {
    padding: 7px;
}

QTableWidget::item:selected,
QListWidget::item:selected {
    background-color: #D8EEF1;
    color: #18313B;
}

QHeaderView::section {
    background-color: #EAF2F4;
    color: #2B5361;
    border: 0;
    border-right: 1px solid #D6E2E6;
    border-bottom: 1px solid #D6E2E6;
    padding: 9px 8px;
    font-weight: 700;
}

QCheckBox {
    spacing: 7px;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
}

QStatusBar {
    background-color: #E8F0F3;
    color: #49656F;
    border-top: 1px solid #D4E0E4;
}

QToolTip {
    background-color: #173D49;
    color: #FFFFFF;
    border: 0;
    padding: 5px;
}
"""
