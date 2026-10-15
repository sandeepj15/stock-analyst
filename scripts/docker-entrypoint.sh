#!/usr/bin/env bash
set -e

# Wait for Postgres to accept connections
echo "Checking Postgres connection..."
python -c "
import asyncio, sys, time
from packages.common.db import get_engine
from sqlalchemy import text

async def wait_db():
    engine = get_engine()
    for attempt in range(60):
        try:
            async with engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            await engine.dispose()
            print('Postgres is ready.')
            return
        except Exception:
            if attempt % 5 == 0:
                print(f'Waiting for Postgres (attempt {attempt + 1}/60)...')
            await asyncio.sleep(1)
    print('Postgres connection timed out after 60s.')
    sys.exit(1)

asyncio.run(wait_db())
"

# Run database migrations and bootstrap initial data if empty
python scripts/bootstrap_db.py

# Execute the container command
exec "$@"
