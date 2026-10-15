import asyncio
import logging
from packages.common.db import session_scope
from packages.common.models import Instrument
from sqlalchemy import select
from packages.scoring.engine import compute_research_score

logging.basicConfig(level=logging.DEBUG)

async def main():
    async with session_scope() as session:
        stmt = select(Instrument).where(Instrument.symbol == "RELIANCE")
        inst = (await session.execute(stmt)).scalar_one()
        score = await compute_research_score(session, inst)
        print("Score:", score)

if __name__ == "__main__":
    asyncio.run(main())
