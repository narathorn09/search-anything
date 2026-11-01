"""Entry point of the installed desktop app (PyInstaller)."""

import multiprocessing

if __name__ == "__main__":
    # Must come first: the scan worker and PDF helper processes start this
    # same executable, and freeze_support() turns those starts into workers.
    multiprocessing.freeze_support()
    from search_anything.desktop import main

    main()
