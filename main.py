"""Start vocabbot. See vocabbot/cli.py, or run `python main.py --help`."""
import multiprocessing

if __name__ == "__main__":
    # Packaged app: libraries start multiprocessing helpers by re-running this executable.
    # freeze_support() hands those runs off before vocabbot itself is imported and started again.
    multiprocessing.freeze_support()

    from vocabbot.cli import run
    run()
