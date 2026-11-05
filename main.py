"""Start vocabbot.

    python main.py          # terminal app (see --help)
    python main.py --gui    # desktop window
The packaged app opens the desktop window when started without arguments.
"""
import multiprocessing
import sys

if __name__ == "__main__":
    # Packaged app: libraries start multiprocessing helpers by re-running this executable.
    # freeze_support() hands those runs off before vocabbot itself is imported and started again.
    multiprocessing.freeze_support()

    from vocabbot.paths import is_frozen

    args = sys.argv[1:]
    if args[:1] == ["--self-test"]:
        from vocabbot.selftest import run as self_test
        sys.exit(self_test(args[1:]))
    if args == ["--gui"] or (is_frozen() and not args):
        from vocabbot.gui import run as run_gui
        sys.exit(run_gui())

    from vocabbot.cli import run
    run()
