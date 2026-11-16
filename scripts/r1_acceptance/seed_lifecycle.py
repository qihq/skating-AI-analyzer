"""Seed synthetic lifecycle fixtures ONLY in a newly created acceptance volume.
These rows are not pipeline outputs and must never be reported as inference evidence.
"""
import asyncio
import os
from pathlib import Path
import shutil
from app.database import AsyncSessionLocal
from app.models import Analysis

async def main():
    assert os.environ.get('R1_SYNTHETIC_FIXTURES')=='1'
    destination=Path('/data/uploads/r1-synthetic-empty.mp4')
    shutil.copy2('/evidence/empty.mp4',destination)
    async with AsyncSessionLocal() as session:
        for state in ['processing','completed','awaiting_target_selection','failed']:
            identity='r1-fixture-'+state
            assert await session.get(Analysis,identity) is None, 'refusing to replace existing rows'
            session.add(Analysis(id=identity,action_type='jump',status=state,video_path=str(destination),
                report={'summary':'Synthetic persistence fixture; NOT an inference result','source':'legacy/local','subscores':{},'technical_conclusion':None},
                target_lock_status='needs_confirmation' if state=='awaiting_target_selection' else None))
        await session.commit()
asyncio.run(main())
