# Vocabulary.com Assistant

A modern GUI application that helps automate vocabulary.com practice sessions using AI assistance.

## Features

- Modern, user-friendly GUI interface with dark theme
- Real-time status updates and logging
- Statistics tracking (correct answers, wrong answers, achievements)
- Configurable browser settings
- Secure API key management
- Support for both multiple choice and audio questions
- Automatic achievement handling
- Start/Stop functionality

## Requirements

- Python 3.8 or higher
- Chrome browser
- OpenAI API key

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/vocabcom-Semi-Auto-Answer.git
cd vocabcom-Semi-Auto-Answer
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Configure your settings:
   - Launch the application
   - Enter your OpenAI API key
   - Adjust browser settings if needed
   - Click "Save Configuration"

## Usage

1. Run the application:
```bash
python vocab_assistant.py
```

2. In the application:
   - Configure your settings if you haven't already
   - Click "Start Automation"
   - Sign in to vocabulary.com when the browser opens
   - Select your assignment
   - The automation will begin automatically

3. Features:
   - Use the Start/Stop button to control the automation
   - Monitor progress in the status window
   - Track statistics in real-time
   - View detailed logs in the log viewer

## Configuration Options

- **API Configuration**
  - OpenAI API Key: Your API key for GPT-3.5 access

- **Browser Settings**
  - Disable GPU: Toggle GPU acceleration
  - No Sandbox: Toggle Chrome sandbox mode
  - Disable Shared Memory: Toggle shared memory usage
  - Window Size: Set browser window dimensions

## Statistics Tracking

The application tracks:
- Correct answers
- Wrong answers
- Achievements unlocked

Statistics are automatically saved and persist between sessions.

## Troubleshooting

1. **Browser Issues**
   - Make sure Chrome is installed
   - Try toggling different browser settings
   - Clear browser cache/cookies if needed

2. **API Issues**
   - Verify your API key is correct
   - Check your OpenAI account status
   - Ensure you have sufficient API credits

3. **Automation Issues**
   - Make sure you're signed in to vocabulary.com
   - Check your internet connection
   - Try restarting the application

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for educational purposes only. Please use responsibly and in accordance with vocabulary.com's terms of service.
