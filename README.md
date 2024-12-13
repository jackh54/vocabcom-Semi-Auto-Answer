# Vocabulary.com Semi-Auto Bot

An semi-automated solution for completing Vocabulary.com assignments using Selenium and OpenAI's GPT-3.5-turbo model.

## Features

- Automatically answers Vocabulary.com questions
- Handles multiple choice questions
- Detects audio questions and prompts for manual intervention
- Supports round completion and automatic reloading
- Uses GPT-3.5 for intelligent answer selection

## Prerequisites

- Python 3.x
- Chrome browser
- OpenAI API key

## Installation

```sh
pip install undetected-chromedriver selenium openai
```

## Configuration

1. Replace the 

openai_api_key

 in the script with your OpenAI API key
2. Ensure Chrome browser is installed

## Usage
*Works on windows & mac*

*Working as of 12/12/24*

1. Run the script:
```sh
python main.py
```

2. Follow the prompts to:
   - Sign in to your Vocabulary.com account
   - Navigate to your assignment
   - Press Enter to start automation
   - Handle audio questions manually when prompted

## Known Issues
- Gets a question wrong (rarely) - fix is to manually select the right one or wait ~30 seconds to eventually guess it.
- Cant recognize questions with images (just do it yourself and press the next button)
- Doesnt recognize achievement pages (just click next button and it will startup again)

## Important Notes

- The script requires manual login for security purposes
- Includes automatic detection for completed rounds
- Uses undetected-chromedriver to avoid detection
- After each round it makes you reclick the assignment due to issues with the html stacking up

## TODO

- [ ] Add retry mechanism for failed questions
- [ ] Implement image question detection
- [ ] Add support for achievement page detection
- [ ] Improve HTML stacking issue after round completion
- [ ] Add logging system for tracking success/error rates
- [ ] Create config file for user settings
- [ ] Create backup mechanism for session state
- [ ] Optimize waiting times between questions
- [ ] Add statistics tracking
- [ ] Add support for different question types
- [ ] Use a .env
  
Feel free to open pull requests :)

## Disclaimer

Using this tool could violate vocab.com's terms if used incorrectly, please use accordingly, im not responsible for how you use it.
