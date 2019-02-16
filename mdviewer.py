import os

from PyQt5 import QtCore, QtGui, QtWidgets, QtPrintSupport, QtWebEngineWidgets
from lxml import html

from utils import cached_property, log

VERSION = '0.3'

script_dir = os.path.dirname(os.path.realpath(__file__))
stylesheet_dir = os.path.join(script_dir, 'stylesheets/')

XPathRole = QtCore.Qt.UserRole + 1000
TagRole = QtCore.Qt.UserRole + 1001

lut = {"h{}".format(i): i for i in range(1, 7)}


class MarkdownWorker(QtCore.QObject):
    htmlChanged = QtCore.pyqtSignal(str)
    warningChanged = QtCore.pyqtSignal(str)

    def __init__(self, processor_path, processor_args, parent=None):
        super(MarkdownWorker, self).__init__(parent)
        self._processor_path = processor_path
        self._processor_args = processor_args
        self.filename = ''

        self.process.finished.connect(self.on_finished)
        self.watcher.fileChanged.connect(self.start_process)

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, filename):
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        if filename:
            self.watcher.addPath(filename)
            self.start_process(filename)
        self._filename = filename

    @cached_property
    def watcher(self):
        return QtCore.QFileSystemWatcher(self)

    @cached_property
    def process(self):
        return QtCore.QProcess(self)

    @log
    @QtCore.pyqtSlot(str)
    def start_process(self, filename):
        if filename:
            args = (('%s' % self._processor_args).split() if self._processor_args else []) + [filename]
            self.process.start(self._processor_path, args)

    @log
    @QtCore.pyqtSlot(int, QtCore.QProcess.ExitStatus)
    def on_finished(self, exitCode, exitStatus):
        if exitCode == 0 and exitStatus == QtCore.QProcess.NormalExit:
            html = self.process.readAllStandardOutput().data().decode('utf8')
            self.htmlChanged.emit(html)
            msg = self.process.readAllStandardError().data().decode('utf8')
            if msg:
                self.warningChanged.emit(msg)


class MDViewer(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super(MDViewer, self).__init__(parent)
        self.setCentralWidget(self.web_view)
        self.tree_view.setModel(self.model)
        self.tree_view.header().hide()
        dock = QtWidgets.QDockWidget("Table of Contents", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        dock.setWidget(self.tree_view)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)

        self.web_view.loadFinished.connect(self.on_load_finished)
        self.markdown_worker.htmlChanged.connect(self.on_html_changed)
        self.markdown_worker.warningChanged.connect(self.statusBar().showMessage)
        self.tree_view.selectionModel().currentChanged.connect(self.on_current_changed)

        self._current_css = ''
        self._m_inPrintPreview = False

        self.search_panel.hide()
        self.addToolBar(QtCore.Qt.BottomToolBarArea, self.search_panel)

        self.create_menus()
        self.create_search_panel()
        self.set_env()

    def create_menus(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu('&File')

        for d in (
                {'label': u'&Open...', 'keys': 'Ctrl+O', 'func': self.open_file},
                {'label': u'&Save HTML...', 'keys': 'Ctrl+S', 'func': self.save_html},
                {'label': u'&Find...', 'keys': 'Ctrl+F', 'func': self.show_search_panel},
                {'label': u'&Print...', 'keys': 'Ctrl+P', 'func': self.print_preview},
                {'label': u'&Quit', 'keys': 'Ctrl+Q', 'func': self.close}
        ):
            action = QtWidgets.QAction(d['label'], self)
            action.setShortcut(d['keys'])
            action.triggered.connect(d['func'])
            file_menu.addAction(action)

        help_menu = menubar.addMenu("&Help")

        for d in (
                {'label': u'About...', 'func': self.about},
        ):
            action = QtWidgets.QAction(d['label'], self)
            action.triggered.connect(d['func'])
            help_menu.addAction(action)

        self.set_stylesheet()

    def create_search_panel(self):
        done_button = QtWidgets.QPushButton('Done')
        self.case_button = QtWidgets.QPushButton('Case')
        self.case_button.setCheckable(True)
        next_button = QtWidgets.QPushButton('Next')
        prev_button = QtWidgets.QPushButton('Previous')

        self.search_le = QtWidgets.QLineEdit()
        shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), self.search_le)
        shortcut.activated.connect(self.search_panel.hide)
        self.search_panel.setFocusProxy(self.search_le)

        done_button.clicked.connect(self.search_panel.hide)
        next_button.clicked.connect(self.find)
        prev_button.clicked.connect(self.on_preview_find)

        for btn in (done_button, self.case_button, self.search_le, next_button, prev_button):
            self.search_panel.addWidget(btn)
            if isinstance(btn, QtWidgets.QPushButton):
                btn.clicked.connect(self.search_panel.setFocus)

        self.search_le.textChanged.connect(self.find)
        self.search_le.returnPressed.connect(self.find)

    def open_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Open File',
                                                            os.path.dirname(self.markdown_worker.filename))
        if filename:
            self.set_env()
            self.load_file(filename)

    def save_html(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save File',
                                                            os.path.dirname(self.markdown_worker.filename))

        def callback(text):
            with open(filename, 'w') as f:
                f.write(text)

        if filename:
            self.web_view.page().toHtml(callback)

    @QtCore.pyqtSlot()
    def on_preview_find(self):
        self.find(QtWebEngineWidgets.QWebEnginePage.FindBackward)

    @QtCore.pyqtSlot()
    def find(self, direction=QtWebEngineWidgets.QWebEnginePage.FindFlag()):
        flag = direction
        if self.case_button.isChecked():
            flag |= QtWebEngineWidgets.QWebEnginePage.FindCaseSensitively

        def callback(found):
            if not found:
                self.statusBar().showMessage("Not found")

        self.web_view.page().findText(self.search_le.text(), flag, callback)

    @QtCore.pyqtSlot()
    def show_search_panel(self):
        self.search_panel.show()
        self.search_panel.setFocus()

    @QtCore.pyqtSlot()
    def about(self):
        msg_about = QtWidgets.QMessageBox(QtWidgets.QMessageBox.NoIcon, 'About MDviewer',
                                          u'MDviewer\n\nVersion: %s' % VERSION, parent=self)
        msg_about.show()

    def set_window_title(self):
        _, name = os.path.split(os.path.abspath(self.markdown_worker.filename))
        self.setWindowTitle(u'%s – MDviewer' % name)

    # https://bugreports.qt.io/browse/QTBUG-57982
    @log
    @QtCore.pyqtSlot()
    def print_preview(self):
        if not self.web_view.page(): return
        if self._m_inPrintPreview: return
        self._m_inPrintPreview = True
        printer = QtPrintSupport.QPrinter()
        dialog = QtPrintSupport.QPrintPreviewDialog(printer, self.web_view)
        dialog.paintRequested.connect(self.print_document)
        dialog.exec()
        self._m_inPrintPreview = False

    @QtCore.pyqtSlot(QtPrintSupport.QPrinter)
    def print_document(self, printer):
        loop = QtCore.QEventLoop()
        setattr(self, "_status_", False)

        def callback(success):
            setattr(self, "_status_", success)
            loop.quit()

        self.web_view.page().print(printer, callback)
        loop.exec_()
        if not getattr(self, "_status_"):
            painter = QtGui.QPainter()
            if painter.begin(printer):
                font = painter.font()
                font.setPixelSize(20)
                painter.setFont(font)
                painter.drawText(QtCore.QPointF(10, 25), "Could not generate print preview.")
                painter.end()

    @log
    def closeEvent(self, event):
        self.settings.beginGroup('Geometry')
        self.settings.setValue('size', self.size())
        self.settings.setValue('pos', self.pos())
        self.settings.endGroup()
        super(MDViewer, self).closeEvent(event)

    @QtCore.pyqtSlot(QtCore.QModelIndex)
    def on_current_changed(self, index):
        xpath = index.data(QtCore.Qt.UserRole + 1000)
        js = '''
        var element = document.evaluate("%s",
            document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        element.scrollIntoView({ block: 'start', behavior: 'smooth' });
        ''' % xpath
        self.web_view.page().runJavaScript(js)

    @QtCore.pyqtSlot(bool)
    def on_load_finished(self, state):
        if state:
            self.web_view.page().toHtml(self.create_toc)

    @log
    def create_toc(self, text):
        root = html.fromstring(text)
        tree = root.getroottree()
        self.model.clear()
        last_item = self.model.invisibleRootItem()
        for e in tree.xpath("//h1|//h2|//h3|//h4|//h5|//h6"):
            it = QtGui.QStandardItem(e.text)
            it.setEditable(False)
            it.setData(str(tree.getpath(e)), XPathRole)
            it.setData(str(e.tag), TagRole)
            last_tag = last_item.data(TagRole)
            if last_tag:
                last_level, current_level = lut[last_tag], lut[e.tag]
                if last_level < current_level:
                    last_item.appendRow(it)
                else:
                    parent_index = last_item.index()
                    while parent_index.isValid():
                        last_tag = parent_index.data(TagRole)
                        last_level = lut[last_tag]
                        if last_level < current_level:
                            current_item = self.model.itemFromIndex(parent_index)
                            current_item.appendRow(it)
                            break
                        parent_index = parent_index.parent()
                    else:
                        self.model.appendRow(it)
            else:
                self.model.appendRow(it)
            last_item = it
        self.tree_view.expandAll()

    @QtCore.pyqtSlot(str)
    def on_html_changed(self, html):
        self.web_view.setHtml(html, baseUrl=QtCore.QUrl.fromLocalFile(
            os.path.join(os.getcwd(), self.markdown_worker.filename)))

    def load_file(self, filename):
        self.markdown_worker.filename = filename
        self.set_window_title()

    @cached_property
    def search_panel(self):
        return QtWidgets.QToolBar()

    @cached_property
    def model(self):
        return QtGui.QStandardItemModel(self)

    @cached_property
    def tree_view(self):
        return QtWidgets.QTreeView()

    @cached_property
    def markdown_worker(self):
        self.settings.beginGroup('processor')
        path = self.settings.value("processor_path", 'pandoc')
        args = self.settings.value("processor_args", '')
        self.settings.endGroup()
        return MarkdownWorker(path, args, self)

    @cached_property
    def settings(self):
        return QtCore.QSettings(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, 'MDviewer', 'MDviewer')

    @cached_property
    def web_view(self):
        return QtWebEngineWidgets.QWebEngineView()

    @log
    def set_stylesheet(self, stylesheet='default.css'):
        full_path = os.path.join(stylesheet_dir, stylesheet)
        with open(full_path, 'r') as f:
            if self._current_css:
                self.remove_stylesheet(self._current_css)
            self.insert_stylesheet(stylesheet, f.read())
            self._current_css = stylesheet

    @log
    def insert_stylesheet(self, name, source, immediately=True):
        script = QtWebEngineWidgets.QWebEngineScript()
        s = """
            (function() {
                css = document.createElement('style');
                css.type = 'text/css';
                css.id = '%s';
                document.head.appendChild(css);
                css.innerText = '%s';
            })()""" % (name, source)

        if immediately:
            self.web_view.page().runJavaScript(s, QtWebEngineWidgets.QWebEngineScript.ApplicationWorld)
        script.setName(name)
        script.setSourceCode(source)
        script.setInjectionPoint(QtWebEngineWidgets.QWebEngineScript.DocumentReady)
        script.setRunsOnSubFrames(True)
        script.setWorldId(QtWebEngineWidgets.QWebEngineScript.ApplicationWorld)
        self.web_view.page().scripts().insert(script)

    @log
    def remove_stylesheet(self, name, immediately=True):
        s = """
            (function() {
                var element = document.getElementById('%s');
                element.outerHTML = '';
                delete element;
            })()""" % name
        if immediately:
            self.web_view.page().runJavaScript(s, QtWebEngineWidgets.QWebEngineScript.ApplicationWorld)
        script = self.web_view.page().scripts().findScript(name)
        self.web_view.page().scripts().remove(script)

    def set_env(self):
        fpath, fname = os.path.split(os.path.abspath(self.markdown_worker.filename))
        fext = fname.split('.')[-1].lower()
        os.environ["MDVIEWER_EXT"] = fext
        os.environ["MDVIEWER_FILE"] = fname
        os.environ["MDVIEWER_ORIGIN"] = fpath


if __name__ == '__main__':
    import sys

    file = os.path.join(script_dir, u'README.md')

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    w = MDViewer()
    w.load_file(file)
    w.showMaximized()
    sys.exit(app.exec_())
