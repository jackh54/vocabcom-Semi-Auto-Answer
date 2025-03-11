import json
from automation import VocabAutomation

def main():
    # Load config
    with open('config.json', 'r') as config_file:
        config = json.load(config_file)
    
    # Create and run automation
    automation = VocabAutomation(config)
    
    try:
        automation.run()
    except KeyboardInterrupt:
        print("\nStopping automation...")
        automation.stop()
    except Exception as e:
        print(f"Error: {str(e)}")
        automation.stop()

if __name__ == "__main__":
    main()
