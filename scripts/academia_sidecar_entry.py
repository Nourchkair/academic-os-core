"""Entry point used to package the self-contained Academia CLI sidecar."""

import multiprocessing

from academia_os.cli import main

if __name__ == "__main__":
    # Packaged builds use a process pool for cold PDF extraction; the frozen
    # runtime needs this guard before workers can start.
    multiprocessing.freeze_support()
    raise SystemExit(main())
