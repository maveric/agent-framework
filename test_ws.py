import asyncio
import websockets
import json

async def test_connection():
    uri = "ws://localhost:8001/ws"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            
            # Send subscribe
            await websocket.send(json.dumps({"type": "subscribe", "run_id": "test_run"}))
            print("Sent subscribe")
            
            # Wait for response or keep alive
            # The server doesn't send an immediate ack for subscribe in the current code, 
            # but we can check if connection stays open.
            await asyncio.sleep(1)
            print("Connection maintained")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
