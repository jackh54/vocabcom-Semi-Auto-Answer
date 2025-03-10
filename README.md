# Vocabulary.com Assistant

A modern GUI application that helps automate vocabulary.com practice sessions using AI assistance.

## Features

- Modern, user-friendly GUI interface with dark theme
- Real-time status updates and logging
- Statistics tracking (correct answers, wrong answers, achievements, cache hits)
- Smart answer caching system
- Configurable browser settings
- Secure API key management
- Support for both multiple choice, image, and audio questions
- Automatic achievement handling
- Start/Stop functionality
- "Ready to Start" confirmation button
- Intelligent retry system for wrong answers
- Automatic round completion handling
- Assignment completion detection

## Requirements

- Python 3.8 or higher
- Chrome browser
- OpenAI API key

## Installation

1. Clone this repository:
```bash
git clone https://github.com/jackh54/vocabcom-Semi-Auto-Answer.git
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
   - Click "Ready to Start" when you're ready to begin
   - The automation will begin processing questions

3. Features:
   - Use the Start/Stop button to control the automation
   - Monitor progress in the status window
   - Track statistics in real-time
   - View detailed logs in the log viewer
   - Automatic caching of correct answers
   - Up to 4 retry attempts for wrong answers
   - Automatic handling of image questions
   - Smart detection of round completion

## Configuration Options

- **API Configuration**
  - OpenAI API Key: Your API key for GPT-3.5 access

- **Browser Settings**
  - Disable GPU: Toggle GPU acceleration
  - No Sandbox: Toggle Chrome sandbox mode
  - Disable Shared Memory: Toggle shared memory usage
  - Window Size: Set browser window dimensions
  - Suppress Chrome Errors: Toggle error logging

## Statistics Tracking

The application tracks:
- Correct answers
- Wrong answers
- Achievements unlocked
- Cache hits (successful use of cached answers)

Statistics and question cache are automatically saved and persist between sessions.

## Smart Caching System

The application includes an intelligent answer caching system:
- Automatically caches correct answers
- Immediately usable for repeated questions
- Case-insensitive matching
- Tracks usage statistics for each cached answer
- Automatically removes incorrect cached answers
- Persists between sessions
- Real-time updates during automation

## Retry System

For regular questions:
- Up to 4 attempts per question
- Remembers previous wrong answers
- Uses AI to suggest different answers each attempt
- Updates cache based on results

For image questions:
- Up to 4 attempts to find correct image
- Systematic testing of each option
- Automatic detection of correct answers

## Assignment Completion

- Automatic detection of completed assignments
- Notification when assignment is complete
- Instructions for starting new assignments
- Saves final statistics and cache
- Graceful cleanup of resources

## Troubleshooting

1. **Browser Issues**
   - Make sure Chrome is installed and up to date
   - Try toggling different browser settings
   - Clear browser cache/cookies if needed
   - Check Activity Monitor for stuck Chrome processes

2. **API Issues**
   - Verify your API key is correct
   - Check your OpenAI account status
   - Ensure you have sufficient API credits

3. **Automation Issues**
   - Make sure you're signed in to vocabulary.com
   - Check your internet connection
   - Try restarting the application
   - Clear the question cache if answers seem incorrect

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for educational purposes only. Please use responsibly and in accordance with vocabulary.com's terms of service.
