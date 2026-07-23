"""Shared visual language for the ECAP desktop interface."""

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
    color: #274C78;
    font-size: 25px;
    font-weight: 700;
}

QLabel#brandFallback {
    color: #376396;
    font-size: 44px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#supportingText {
    color: #5B727C;
    font-size: 14px;
}

QScrollArea#configurationScroll,
QWidget#configurationContent {
    background-color: #F3F7F9;
    border: 0;
}

QScrollBar:vertical {
    background-color: #E7EFF2;
    width: 11px;
    margin: 2px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #9DB7C0;
    min-height: 34px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #789AA6;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    height: 0;
    background: transparent;
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
    min-height: 24px;
    padding: 6px 9px;
    selection-background-color: #376396;
    selection-color: #FFFFFF;
}

QLineEdit:focus,
QSpinBox:focus,
QDateEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus {
    border: 2px solid #376396;
    padding: 5px 8px;
}

QPushButton {
    min-height: 34px;
    padding: 5px 16px;
    border: 1px solid #BDD0D7;
    border-radius: 7px;
    background-color: #FFFFFF;
    color: #376396;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #EDF2F8;
    border-color: #8FA9C6;
}

QPushButton:pressed {
    background-color: #DDE7F2;
}

QPushButton:disabled {
    background-color: #E9EFF1;
    border-color: #D7E1E4;
    color: #94A5AC;
}

QPushButton#primaryButton,
QPushButton#heroPrimaryButton {
    background-color: #376396;
    border-color: #376396;
    color: #FFFFFF;
}

QPushButton#primaryButton:hover,
QPushButton#heroPrimaryButton:hover {
    background-color: #2F5683;
    border-color: #2F5683;
}

QPushButton#primaryButton:pressed,
QPushButton#heroPrimaryButton:pressed {
    background-color: #27486E;
    border-color: #27486E;
}

QPushButton#secondaryButton,
QPushButton#heroSecondaryButton {
    background-color: #EAF0F7;
    border-color: #376396;
    color: #376396;
}

QPushButton#secondaryButton:hover,
QPushButton#heroSecondaryButton:hover {
    background-color: #DCE6F1;
    border-color: #7E9DBF;
}

QPushButton#heroPrimaryButton,
QPushButton#heroSecondaryButton {
    min-width: 310px;
    min-height: 58px;
    font-size: 16px;
    border-radius: 10px;
}

QPushButton#navigationButton {
    background-color: #376396;
    border-color: #376396;
    color: #FFFFFF;
    min-height: 36px;
    padding: 5px 15px;
    font-size: 14px;
    font-weight: 700;
}

QPushButton#navigationButton:hover {
    background-color: #2F5683;
    border-color: #2F5683;
}

QPushButton#navigationButton:pressed {
    background-color: #27486E;
    border-color: #27486E;
}

QPushButton#dangerButton {
    background-color: #FCE8EC;
    border-color: #CF5369;
    color: #A72E43;
    font-weight: 700;
}

QPushButton#dangerButton:hover {
    background-color: #F8D5DC;
    border-color: #B93F55;
    color: #8E2236;
}

QPushButton#dangerButton:pressed {
    background-color: #F2C2CC;
    border-color: #A72E43;
}

QPushButton#dangerButton:disabled {
    background-color: #F1E9EB;
    border-color: #DDCDD1;
    color: #AD9CA0;
}

QLabel#shortcutHint {
    color: #64788E;
    font-size: 12px;
    font-weight: 600;
}

QFrame#studyControlsPanel,
QFrame#snapshotsPanel {
    background-color: #FFFFFF;
    border: 1px solid #D8E4E8;
    border-radius: 10px;
}

QLabel#panelLabel {
    color: #66808A;
    font-size: 12px;
    font-weight: 700;
}

QLabel#patientSummary {
    color: #173D49;
    font-size: 14px;
    font-weight: 650;
}

QLabel#workflowStatus {
    color: #2F5683;
    background-color: #EAF0F7;
    border-radius: 6px;
    padding: 8px 10px;
    font-weight: 650;
}

QFrame#panelSeparator {
    color: #D8E4E8;
    background-color: #D8E4E8;
    max-height: 1px;
}

QLabel#snapshotsTitle {
    color: #234D5C;
    font-size: 16px;
    font-weight: 700;
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
    background-color: #DDE7F2;
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
