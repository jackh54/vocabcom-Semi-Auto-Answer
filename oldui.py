import sys
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                            QTextEdit, QGroupBox, QFormLayout, QSpinBox,
                            QCheckBox, QMessageBox, QProgressBar, QPlainTextEdit,
                            QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QFont, QPalette, QColor
import logging
from automation import VocabAutomation
from time import sleep

class QTextEditLogger(logging.Handler):
    def __init__(self, parent):
        super().__init__()
        self.widget = QPlainTextEdit(parent)
        self.widget.setReadOnly(True)
        self.widget.setMaximumBlockCount(500)  # Limit number of lines for performance
        self.widget.setStyleSheet("""
            QPlainTextEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 2px;
                font-family: 'Menlo', 'Monaco', monospace;
            }
        """)

    def emit(self, record):
        msg = self.format(record)
        self.widget.appendPlainText(msg)
        self.widget.verticalScrollBar().setValue(
            self.widget.verticalScrollBar().maximum()
        )

class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_config()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # API Configuration
        api_group = QGroupBox("API Configuration")
        api_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #555555;
                border-radius: 6px;
                margin-top: 1em;
                padding-top: 10px;
            }
            QGroupBox::title {
                color: white;
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        api_layout = QFormLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        api_layout.addRow("OpenAI API Key:", self.api_key_input)
        api_group.setLayout(api_layout)
        
        # Browser Configuration
        browser_group = QGroupBox("Browser Settings")
        browser_group.setStyleSheet(api_group.styleSheet())
        browser_layout = QFormLayout()
        
        self.disable_gpu = QCheckBox()
        self.no_sandbox = QCheckBox()
        self.disable_shm = QCheckBox()
        self.suppress_errors = QCheckBox()
        
        self.window_width = QSpinBox()
        self.window_width.setRange(800, 3840)
        self.window_width.setValue(1920)
        
        self.window_height = QSpinBox()
        self.window_height.setRange(600, 2160)
        self.window_height.setValue(1080)
        
        for checkbox in [self.disable_gpu, self.no_sandbox, self.disable_shm, self.suppress_errors]:
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: white;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                }
            """)
        
        for spinbox in [self.window_width, self.window_height]:
            spinbox.setStyleSheet("""
                QSpinBox {
                    background-color: #333333;
                    color: white;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    padding: 5px;
                }
            """)
        
        browser_layout.addRow("Disable GPU:", self.disable_gpu)
        browser_layout.addRow("No Sandbox:", self.no_sandbox)
        browser_layout.addRow("Disable Shared Memory:", self.disable_shm)
        browser_layout.addRow("Suppress Chrome Errors:", self.suppress_errors)
        browser_layout.addRow("Window Width:", self.window_width)
        browser_layout.addRow("Window Height:", self.window_height)
        
        browser_group.setLayout(browser_layout)
        
        # Save Button
        save_btn = QPushButton("Save Configuration")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
            QPushButton:pressed {
                background-color: #0a3d91;
            }
        """)
        save_btn.clicked.connect(self.save_config)
        
        layout.addWidget(api_group)
        layout.addWidget(browser_group)
        layout.addWidget(save_btn)
        layout.addStretch()
        
        self.setLayout(layout)

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                self.api_key_input.setText(config.get('openai_api_key', ''))
                
                chrome_options = config.get('chrome_options', {})
                self.disable_gpu.setChecked(chrome_options.get('disable_gpu', True))
                self.no_sandbox.setChecked(chrome_options.get('no_sandbox', True))
                self.disable_shm.setChecked(chrome_options.get('disable_dev_shm_usage', True))
                self.suppress_errors.setChecked(chrome_options.get('suppress_errors', True))
                
                if 'window_size' in chrome_options:
                    width, height = map(int, chrome_options['window_size'].split(','))
                    self.window_width.setValue(width)
                    self.window_height.setValue(height)
        except FileNotFoundError:
            pass

    def save_config(self):
        config = {
            'openai_api_key': self.api_key_input.text(),
            'chrome_options': {
                'disable_gpu': self.disable_gpu.isChecked(),
                'no_sandbox': self.no_sandbox.isChecked(),
                'disable_dev_shm_usage': self.disable_shm.isChecked(),
                'suppress_errors': self.suppress_errors.isChecked(),
                'window_size': f"{self.window_width.value()},{self.window_height.value()}"
            }
        }
        
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
            
        QMessageBox.information(self, "Success", "Configuration saved successfully!")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.automation_thread = None
        self.setup_logging()
        self.init_ui()
        self._cleanup_in_progress = False

    def setup_logging(self):
        self.log_handler = QTextEditLogger(self)
        self.log_handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

    def init_ui(self):
        self.setWindowTitle("Vocabulary.com Assistant")
        self.setMinimumSize(1000, 800)
        
        # Set the window style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QLabel {
                color: white;
                font-size: 14px;
            }
            QGroupBox {
                color: white;
            }
        """)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create top control panel
        control_panel = QHBoxLayout()
        
        # Start/Stop button
        self.toggle_btn = QPushButton("Start Automation")
        self.toggle_btn.setFixedSize(150, 40)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton[running="true"] {
                background-color: #e74c3c;
            }
            QPushButton[running="true"]:hover {
                background-color: #c0392b;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_automation)

        # Ready to Start button
        self.ready_btn = QPushButton("Ready to Start")
        self.ready_btn.setFixedSize(150, 40)
        self.ready_btn.setEnabled(False)
        self.ready_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #7f8c8d;
            }
        """)
        self.ready_btn.clicked.connect(self.ready_to_start)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #2ecc71;
                font-weight: bold;
                font-size: 14px;
                padding: 5px;
                background-color: #2b2b2b;
                border-radius: 4px;
            }
        """)
        
        control_panel.addWidget(self.toggle_btn)
        control_panel.addWidget(self.ready_btn)
        control_panel.addWidget(self.status_label)
        control_panel.addStretch()
        
        # Create statistics panel
        stats_group = QGroupBox("Statistics")
        stats_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #555555;
                border-radius: 6px;
                margin-top: 1em;
                padding: 10px;
            }
            QGroupBox::title {
                color: white;
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        stats_layout = QHBoxLayout()
        
        self.correct_label = QLabel("Correct: 0")
        self.wrong_label = QLabel("Wrong: 0")
        self.achievements_label = QLabel("Achievements: 0")
        
        for label in [self.correct_label, self.wrong_label, self.achievements_label]:
            label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-size: 14px;
                    padding: 5px 10px;
                    background-color: #2b2b2b;
                    border-radius: 4px;
                    min-width: 120px;
                }
            """)
        
        stats_layout.addWidget(self.correct_label)
        stats_layout.addWidget(self.wrong_label)
        stats_layout.addWidget(self.achievements_label)
        stats_layout.addStretch()
        
        stats_group.setLayout(stats_layout)
        
        # Config widget
        self.config_widget = ConfigWidget()
        
        # Create log viewer with title
        log_group = QGroupBox("Log Output")
        log_group.setStyleSheet(stats_group.styleSheet())
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_handler.widget)
        log_group.setLayout(log_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                text-align: center;
                background-color: #2b2b2b;
            }
            QProgressBar::chunk {
                background-color: #2ecc71;
                width: 10px;
                margin: 0.5px;
            }
        """)
        self.progress_bar.hide()
        
        # Add all widgets to main layout
        layout.addLayout(control_panel)
        layout.addWidget(stats_group)
        layout.addWidget(self.config_widget)
        layout.addWidget(log_group)
        layout.addWidget(self.progress_bar)

    def toggle_automation(self):
        if self.automation_thread is None or not self.automation_thread.isRunning():
            self.start_automation()
        else:
            self.stop_automation()

    def start_automation(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
            
            self.automation_thread = AutomationThread(config)
            self.automation_thread.status_update.connect(self.update_status)
            self.automation_thread.stats_update.connect(self.update_stats)
            self.automation_thread.error_occurred.connect(self.handle_error)
            self.automation_thread.log_message.connect(self.log_message)
            self.automation_thread.automation_completed.connect(self.handle_completion)
            
            self.automation_thread.start()
            
            self.toggle_btn.setText("Stop Automation")
            self.toggle_btn.setProperty("running", True)
            self.toggle_btn.setStyleSheet(self.toggle_btn.styleSheet())
            self.ready_btn.setEnabled(True)
            self.progress_bar.show()
            self.config_widget.setEnabled(False)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def stop_automation(self):
        """Stop automation and cleanup resources"""
        if self._cleanup_in_progress:
            return

        self._cleanup_in_progress = True
        try:
            if self.automation_thread:
                if self.automation_thread.isRunning():
                    self.automation_thread.stop()
                    self.automation_thread.wait(5000)  # Wait up to 5 seconds
                self.automation_thread = None

            self.toggle_btn.setText("Start Automation")
            self.toggle_btn.setProperty("running", False)
            self.toggle_btn.setStyleSheet(self.toggle_btn.styleSheet())
            self.ready_btn.setEnabled(False)
            self.progress_bar.hide()
            self.config_widget.setEnabled(True)
        finally:
            self._cleanup_in_progress = False

    def ready_to_start(self):
        if self.automation_thread and self.automation_thread.isRunning():
            self.automation_thread.automation.set_ready()
            self.ready_btn.setEnabled(False)
            self.update_status("Automation starting...")

    def update_status(self, status):
        self.status_label.setText(status)

    def update_stats(self, stats):
        self.correct_label.setText(f"Correct: {stats['correct_answers']}")
        self.wrong_label.setText(f"Wrong: {stats['wrong_answers']}")
        self.achievements_label.setText(f"Achievements: {stats['achievements']}")

    def handle_error(self, error_msg):
        QMessageBox.critical(self, "Error", error_msg)
        self.stop_automation()

    def log_message(self, message):
        logging.info(message)

    def handle_completion(self):
        """Handle automation completion on the main thread"""
        if not self._cleanup_in_progress:
            self.stop_automation()
            QMessageBox.information(self, "Assignment Complete", 
                "The current assignment has been completed!\n\n"
                "To start a new assignment:\n"
                "1. Select your next assignment\n"
                "2. Click 'Start Automation'\n"
                "3. Click 'Ready to Start' when ready"
            )

    def closeEvent(self, event):
        """Handle application close event"""
        self._cleanup_in_progress = True
        try:
            # Stop automation if running
            if self.automation_thread:
                if self.automation_thread.isRunning():
                    self.automation_thread.stop()
                    self.automation_thread.wait(5000)  # Wait up to 5 seconds
                self.automation_thread = None

            # Close any open file handles
            logging.getLogger().removeHandler(self.log_handler)
            if hasattr(self.log_handler.widget, 'document'):
                self.log_handler.widget.document().clear()

            # Accept the close event
            event.accept()
        finally:
            self._cleanup_in_progress = False
            QApplication.quit()

class AutomationThread(QThread):
    status_update = pyqtSignal(str)
    stats_update = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)
    automation_completed = pyqtSignal()  # Signal for completion

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.automation = None
        self.running = True

    def run(self):
        try:
            self.automation = VocabAutomation(
                self.config,
                status_callback=self.handle_status,
                stats_callback=self.handle_stats,
                log_callback=self.handle_log
            )
            
            # Set completion callback
            self.automation.set_completion_callback(self.handle_completion)
            
            self.automation.run()
            
        except Exception as e:
            self.error_occurred.emit(str(e))
            logging.error(f"Error in automation thread: {str(e)}")
        finally:
            self.cleanup()

    def handle_completion(self):
        """Handle automation completion by emitting signal to main thread"""
        self.automation_completed.emit()

    def handle_status(self, status):
        self.status_update.emit(status)

    def handle_stats(self, stats):
        self.stats_update.emit(stats)

    def handle_log(self, message):
        self.log_message.emit(message)

    def stop(self):
        if self.automation:
            self.automation.stop()
        self.running = False

    def cleanup(self):
        try:
            if self.automation:
                self.automation.cleanup()
        except Exception as e:
            logging.error(f"Error in cleanup: {str(e)}")

def main():
    app = QApplication(sys.argv)
    
    # Set application-wide style
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(43, 43, 43))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 