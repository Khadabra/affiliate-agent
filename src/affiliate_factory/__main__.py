"""Package entrypoint for `python -m affiliate_factory`."""

import sys
from affiliate_factory.cli import main

if __name__ == "__main__":
    sys.exit(main())
