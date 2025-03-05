import sys
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                            QTextEdit, QGroupBox, QFormLayout, QSpinBox,
                            QCheckBox, QMessageBox, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFont
from qt_material import apply_stylesheet
from automation import VocabAutomation

class AutomationThread(QThread):
    status_update = pyqtSignal(str)
    stats_update = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True

    def run(self):
        try:
            self.automation = VocabAutomation(self.config)
            self.automation.status_callback = self.status_update.emit
            self.automation.stats_callback = self.stats_update.emit
            self.automation.run()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self.running = False
        if hasattr(self, 'automation'):
            self.automation.stop()

class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_config()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # API Configuration
        api_group = QGroupBox("API Configuration")
        api_layout = QFormLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addRow("OpenAI API Key:", self.api_key_input)
        api_group.setLayout(api_layout)
        
        # Browser Configuration
        browser_group = QGroupBox("Browser Settings")
        browser_layout = QFormLayout()
        
        self.disable_gpu = QCheckBox()
        self.no_sandbox = QCheckBox()
        self.disable_shm = QCheckBox()
        
        self.window_width = QSpinBox()
        self.window_width.setRange(800, 3840)
        self.window_width.setValue(1920)
        
        self.window_height = QSpinBox()
        self.window_height.setRange(600, 2160)
        self.window_height.setValue(1080)
        
        browser_layout.addRow("Disable GPU:", self.disable_gpu)
        browser_layout.addRow("No Sandbox:", self.no_sandbox)
        browser_layout.addRow("Disable Shared Memory:", self.disable_shm)
        browser_layout.addRow("Window Width:", self.window_width)
        browser_layout.addRow("Window Height:", self.window_height)
        
        browser_group.setLayout(browser_layout)
        
        # Save Button
        save_btn = QPushButton("Save Configuration")
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
                'window_size': f"{self.window_width.value()},{self.window_height.value()}"
            }
        }
        
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
            
        QMessageBox.information(self, "Success", "Configuration saved successfully!")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.automation_thread = None

    def init_ui(self):
        self.setWindowTitle("Vocabulary.com Assistant")
        self.setMinimumSize(800, 600)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create top control panel
        control_panel = QHBoxLayout()
        
        # Start/Stop button
        self.toggle_btn = QPushButton("Start Automation")
        self.toggle_btn.setFixedSize(150, 40)
        self.toggle_btn.clicked.connect(self.toggle_automation)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        control_panel.addWidget(self.toggle_btn)
        control_panel.addWidget(self.status_label)
        control_panel.addStretch()
        
        # Create statistics panel
        stats_group = QGroupBox("Statistics")
        stats_layout = QHBoxLayout()
        
        self.correct_label = QLabel("Correct: 0")
        self.wrong_label = QLabel("Wrong: 0")
        self.achievements_label = QLabel("Achievements: 0")
        
        stats_layout.addWidget(self.correct_label)
        stats_layout.addWidget(self.wrong_label)
        stats_layout.addWidget(self.achievements_label)
        
        stats_group.setLayout(stats_layout)
        
        # Create log viewer
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.hide()
        
        # Config widget
        self.config_widget = ConfigWidget()
        
        # Add all widgets to main layout
        layout.addLayout(control_panel)
        layout.addWidget(stats_group)
        layout.addWidget(self.config_widget)
        layout.addWidget(self.log_viewer)
        layout.addWidget(self.progress_bar)
        
        # Apply dark theme
        self.apply_theme()

    def apply_theme(self):
        apply_stylesheet(self, theme='dark_teal.xml')
        # Improve contrast for text
        self.status_label.setStyleSheet('color: white;')
        self.correct_label.setStyleSheet('color: white;')
        self.wrong_label.setStyleSheet('color: white;')
        self.achievements_label.setStyleSheet('color: white;')
        self.log_viewer.setStyleSheet('color: white; background-color: #2a2a2a;')

    def toggle_automation(self):
        if self.automation_thread is None or not self.automation_thread.isRunning():
            self.start_automation()
        else:
            self.stop_automation()

    def start_automation(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            QMessageBox.warning(self, "Error", "Please save configuration first!")
            return

        self.automation_thread = AutomationThread(config)
        self.automation_thread.status_update.connect(self.update_status)
        self.automation_thread.stats_update.connect(self.update_stats)
        self.automation_thread.error_occurred.connect(self.handle_error)
        
        self.automation_thread.start()
        self.toggle_btn.setText("Stop Automation")
        self.progress_bar.show()
        self.config_widget.setEnabled(False)

    def stop_automation(self):
        if self.automation_thread:
            self.automation_thread.stop()
            self.automation_thread.wait()
            self.automation_thread = None
            
        self.toggle_btn.setText("Start Automation")
        self.progress_bar.hide()
        self.config_widget.setEnabled(True)

    def update_status(self, status):
        self.status_label.setText(status)
        self.log_viewer.append(status)
        self.log_viewer.verticalScrollBar().setValue(
            self.log_viewer.verticalScrollBar().maximum()
        )

    def update_stats(self, stats):
        self.correct_label.setText(f"Correct: {stats['correct_answers']}")
        self.wrong_label.setText(f"Wrong: {stats['wrong_answers']}")
        self.achievements_label.setText(f"Achievements: {stats['achievements']}")

    def handle_error(self, error_msg):
        QMessageBox.critical(self, "Error", error_msg)
        self.stop_automation()

    def closeEvent(self, event):
        if self.automation_thread and self.automation_thread.isRunning():
            self.stop_automation()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 