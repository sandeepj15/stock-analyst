import asyncio
from packages.common.db import session_scope
from packages.common.models import Instrument
from sqlalchemy import select
from packages.scoring.engine import compute_research_score
import logging
logging.basicConfig(level=logging.DEBUG)

async def main():
    try:
        async with session_scope() as session:
            stmt = select(Instrument).where(Instrument.symbol == "HAZOOR")
            inst = (await session.execute(stmt)).scalar_one()
            score = await compute_research_score(session, inst)
            print("Score:", score)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
