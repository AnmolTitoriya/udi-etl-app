"""Run the API with uvicorn, ensuring the event loop policy is set before
uvicorn creates its loop.

Running `uvicorn api.main:app` via its CLI creates the event loop before
importing the app module, so the WindowsSelectorEventLoopPolicy set inside
api/main.py never takes effect on Windows (psycopg's async mode then fails
with "Psycopg cannot use the 'ProactorEventLoop'"). Setting the policy here,
before uvicorn.run() is called, fixes that.
"""

import asyncio
import platform

from dotenv import load_dotenv

import uvicorn

if __name__ == "__main__":
    load_dotenv()

    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config("api.main:app", host="0.0.0.0", port=8000)
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())
    else:
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
