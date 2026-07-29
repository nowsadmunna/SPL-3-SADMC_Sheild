import asyncio
import logging
from .main import SADMCAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sadmc-agent")

async def main():
    logger.info("Starting SADMC Shield Agent...")
    agent = SADMCAgent()
    try:
        await agent.run()
    except Exception as e:
        logger.error(f"Agent crashed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
