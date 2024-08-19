import asyncio
import sys
import time
from aio_pika import connect_robust
from aio_pika.patterns import RPC

async def main(query: str) -> None:
    connection = await connect_robust(
        "amqp://admin:adminpassword@192.168.0.52/",
        client_properties={"connection_name": "caller"},
    )

    async with connection:
        # Creating channel
        channel = await connection.channel()

        rpc = await RPC.create(channel)

        start_time = time.time()
        result = await rpc.proxy.call_node_smarthome_agent(query=query)
        end_time = time.time()

        print(result)
        print(f"Time elapsed: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_call_agent.py 'your query here'")
        sys.exit(1)
    
    query = sys.argv[1]
    asyncio.run(main(query))
