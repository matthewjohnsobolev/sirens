import asyncio
import sys

from bi.main import main

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
