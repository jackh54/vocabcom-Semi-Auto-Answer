# Vocabulary.com Automation

A Python-based automation tool for Vocabulary.com that uses GPT-3.5 to assist with vocabulary learning.

## 🚀 Features

- Automated answer selection using GPT-3.5
- Smart caching system for previously answered questions
- Terminal-based UI with real-time statistics
- Automatic handling of audio questions
- Progress tracking and achievement monitoring
- Crash recovery and session persistence

## 📋 Requirements

- Python 3.8+
- Chrome browser
- OpenAI API key

## 🛠️ Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/vocabcom-Semi-Auto-Answer.git
cd vocabcom-Semi-Auto-Answer
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Create a `config.json` file:
```json
{
    "openai_api_key": "your-api-key-here",
    "chrome_options": {
        "no_sandbox": true,
        "disable_gpu": true,
        "disable_dev_shm_usage": true
    },
    "enable_logging": false,
    "log_level": "INFO"
}
```

## 🎮 Usage

1. Run the automation:
```bash
python main.py
```

2. Follow the terminal prompts:
   - Sign in to Vocabulary.com in the browser window
   - Select your assignment
   - Press Enter in the terminal to start

3. Monitor progress in the terminal UI:
   - Top left: Statistics (correct/wrong answers, achievements)
   - Top right: Current status
   - Bottom: Current question

4. Press Ctrl+C to stop the automation gracefully

## ⚙️ Configuration Options

### Chrome Options
- `no_sandbox`: Runs Chrome without sandbox (required for some systems)
- `disable_gpu`: Disables GPU acceleration
- `disable_dev_shm_usage`: Handles shared memory issues

### Logging Options
- `enable_logging`: Enable/disable logging (true/false)
- `log_level`: Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

## 📊 Features in Detail

### Answer Caching
- Automatically caches correct answers
- Reduces API calls for repeated questions
- Cache persists between sessions
- Automatic cache cleanup for old entries

### Statistics Tracking
- Correct/wrong answer counts
- Achievement tracking
- Session duration
- Cache hit/miss ratio

### Error Handling
- Automatic recovery from browser crashes
- Session persistence
- Graceful error handling
- Detailed logging (when enabled)

## ⚠️ Important Notes

1. This tool is for educational purposes only
2. Ensure you have permission to use automation tools on Vocabulary.com
3. Keep your OpenAI API key secure
4. The tool requires a stable internet connection

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.
