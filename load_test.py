import asyncio
import aiohttp
import json
from datetime import datetime

async def submit_scan(session, agent_num):
    url = "http://test06:8000/api/v1/scans/submit"
    data = {
        "agent_id": "18873e0c-5636-44cd-a13f-b4f5753e6484",
        "timestamp": datetime.utcnow().isoformat(),
        "files": [
            {
                "path": f"/tmp/test_agent_{agent_num}.txt",
                "size": 1024,
                "permissions": "0644",
                "owner": 0,
                "group": 0,
                "modified_time": datetime.utcnow().isoformat(),
                "hash": f"hash_{agent_num}"
            }
        ],
        "total_files": 1
    }
    
    async with session.post(url, json=data) as resp:
        return resp.status

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [submit_scan(session, i) for i in range(100)]
        results = await asyncio.gather(*tasks)
        
        success = sum(1 for r in results if r == 200)
        print(f"✅ {success}/100 scans succeeded")
        print(f"❌ {100-success}/100 scans failed")

if __name__ == "__main__":
    asyncio.run(main())
