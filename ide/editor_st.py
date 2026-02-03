# parte 7/9 — ide/editor_st.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ide.config import CODE_FONT_FAMILY, CODE_FONT_SIZE_PT, LINE_NUMBER_GAP_CM


class LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor: "StEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self._editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        self._editor.lineNumberAreaPaintEvent(event)


class StEditor(QtWidgets.QPlainTextEdit):
    def __init__(self, file_path: Path) -> None:
        super().__init__()
        self.file_path = file_path
        self.display_title: Optional[str] = None
        self._dirty = False

        f = QtGui.QFont(CODE_FONT_FAMILY, CODE_FONT_SIZE_PT)
        self.setFont(f)
        self.document().setDefaultFont(f)

        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * QtGui.QFontMetrics(self.font()).horizontalAdvance(" "))

        self.textChanged.connect(self._on_changed)

        self._ln_area = LineNumberArea(self)
        self._ln_area.setFont(self.font())

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()

        self.load_from_disk()

    def _gap_px(self) -> int:
        dpi = float(self.logicalDpiX() or 96.0)
        return int((LINE_NUMBER_GAP_CM * dpi) / 2.54)

    def _on_changed(self) -> None:
        self._dirty = True

    def is_dirty(self) -> bool:
        return self._dirty

    def load_from_disk(self) -> None:
        txt = self.file_path.read_text(encoding="utf-8")
        self.blockSignals(True)
        self.setPlainText(txt)
        self.blockSignals(False)
        self._dirty = False

    def save_to_disk(self) -> None:
        self.file_path.write_text(self.toPlainText(), encoding="utf-8")
        self._dirty = False

    def lineNumberAreaWidth(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        fm = self.fontMetrics()
        return 8 + fm.horizontalAdvance("9") * digits

    def updateLineNumberAreaWidth(self, _newBlockCount: int) -> None:
        self.setViewportMargins(self.lineNumberAreaWidth() + self._gap_px(), 0, 0, 0)

    def updateLineNumberArea(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self._ln_area.scroll(0, dy)
        else:
            self._ln_area.update(0, rect.y(), self._ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._ln_area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self._ln_area)
        painter.fillRect(event.rect(), QtGui.QColor(245, 245, 245))
        painter.setPen(QtGui.QColor(120, 120, 120))

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                h = int(self.blockBoundingRect(block).height())
                if (top + h) >= event.rect().top():
                    painter.drawText(
                        0,
                        top,
                        self._ln_area.width() - 4,
                        h,
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                        str(blockNumber + 1),
                    )
                top += h
            block = block.next()
            blockNumber += 1

    def highlightCurrentLine(self) -> None:
        extraSelections: list[QtWidgets.QTextEdit.ExtraSelection] = []
        if not self.isReadOnly():
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(QtGui.QColor(250, 250, 230))
            selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)
        self.setExtraSelections(extraSelections)
