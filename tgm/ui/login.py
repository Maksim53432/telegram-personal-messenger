"""Sign-in: phone number, code, then the two-step password if the account has one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ..service import PasswordNeeded
from ..tasks import describe_error, spawn


class LoginPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("EmptyState")
        self.setAttribute(Qt.WA_StyledBackground)

        self.title = QLabel("Вход в Telegram", objectName="BigTitle", alignment=Qt.AlignCenter)
        self.hint = QLabel(alignment=Qt.AlignCenter, objectName="Muted")
        self.hint.setWordWrap(True)
        self.error = QLabel(alignment=Qt.AlignCenter, objectName="ErrorText")
        self.error.setWordWrap(True)

        self.phone = QLineEdit(placeholderText="+7 999 123-45-67")
        self.code = QLineEdit(placeholderText="Код")
        self.password = QLineEdit(placeholderText="Пароль", echoMode=QLineEdit.Password)
        self.fields = QStackedWidget()
        for f in (self.phone, self.code, self.password):
            f.setMinimumHeight(40)
            self.fields.addWidget(f)
            f.returnPressed.connect(self._next)
        self.fields.setFixedHeight(44)
        self.button = QPushButton("Далее")
        self.button.clicked.connect(self._next)

        box = QWidget()
        box.setFixedWidth(340)
        col = QVBoxLayout(box)
        col.setSpacing(12)
        for w in (self.title, self.hint, self.fields, self.button, self.error):
            col.addWidget(w)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(box, 0, Qt.AlignHCenter)
        lay.addStretch(2)
        self._step(0)

    def _step(self, index: int) -> None:
        self.fields.setCurrentIndex(index)
        self.hint.setText([
            "Введите номер телефона в международном формате.",
            "Код пришёл в Telegram на другом устройстве или по SMS.",
            "На аккаунте включена двухэтапная проверка. Введите облачный пароль.",
        ][index])
        self.fields.currentWidget().setFocus()

    def _busy(self, busy: bool) -> None:
        self.button.setEnabled(not busy)
        self.fields.setEnabled(not busy)
        if not busy:
            self.fields.currentWidget().setFocus()

    def _next(self) -> None:
        step = self.fields.currentIndex()
        value = self.fields.currentWidget().text().strip()
        if not value:
            return
        self.error.clear()
        self._busy(True)

        async def run():
            try:
                if step == 0:
                    await self.service.send_code(value)
                    self._step(1)
                elif step == 1:
                    try:
                        await self.service.sign_in_code(value)
                    except PasswordNeeded:
                        self._step(2)
                else:
                    await self.service.sign_in_password(self.password.text())
            except Exception as exc:
                self.error.setText(describe_error(exc))
            finally:
                self._busy(False)

        spawn(run(), quiet=True)
