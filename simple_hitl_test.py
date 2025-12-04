"""
Simple HITL Test - Direct API Test
===================================

Tests the HITL endpoints directly without complex database setup.
This is the fastest way to test the UI integration.

Usage:
    python simple_hitl_test.py
"""

import requests
import json

BASE_URL = "http://localhost:8085"

def test_interrupt_endpoints():
    """Test the interrupt endpoints are working."""
    
    print("="*60)
    print("HITL API Test - Simple Approach")
    print("="*60)
    print("\n1. First, create a normal run via API")
    print("2. We'll manually check for interrupts")
    print("3. Then test the resolution endpoint\n")
    
    # Test 1: Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/api/runs")
        print("✅ Server is running")
        runs = response.json()
        print(f"   Found {len(runs)} existing runs\n")
    except Exception as e:
        print(f"❌ Server not running: {e}")
        print("   Start server with: python src/server.py")
        return
    
    # Test 2: If there are runs, check for interrupts
    if runs:
        run_id = runs[0]["run_id"]
        print(f"Testing with existing run: {run_id}\n")
        
        # Check for interrupts
        print("Testing GET /api/runs/{run_id}/interrupts...")
        try:
            response = requests.get(f"{BASE_URL}/api/runs/{run_id}/interrupts")
            data = response.json()
            print(f"✅ Response: {json.dumps(data, indent=2)}\n")
            
            if data.get("interrupted"):
                print("🎯 Found an interrupted run!")
                print(f"   Interrupt data: {json.dumps(data['data'], indent=2)}\n")
                
                # Test resolution endpoint
                test_resolution(run_id)
            else:
                print("ℹ️  No interrupts found (expected if no tasks have failed)\n")
                
        except Exception as e:
            print(f"❌ Error checking interrupts: {e}\n")
    
    # Instructions for creating a failing task
    print("="*60)
    print("To Test HITL Flow:")
    print("="*60)
    print("\n1. Create a run that will fail:")
    print("   curl -X POST http://localhost:8085/api/runs \\")
    print("     -H 'Content-Type: application/json' \\")
    print("     -d '{")
    print("       \"objective\": \"Create a Python file that imports a non-existent module called fake_module_xyz\"")
    print("     }'")
    print("\n2. Wait for it to fail 4 times (check server logs for 'requesting human intervention')")
    print("\n3. Open dashboard at http://localhost:3000")
    print("   - The InterruptModal should appear automatically")
    print("   - Try each resolution action (retry, spawn, abandon)")
    print("\n4. Or test resolution via API:")
    print("   curl -X POST http://localhost:8085/api/runs/{run_id}/resolve \\")
    print("     -H 'Content-Type: application/json' \\")
    print("     -d '{\"action\": \"retry\", \"modified_description\": \"Try again with valid import\"}'")
    print("\n" + "="*60)


def test_resolution(run_id: str):
    """Test the resolution endpoint with a retry action."""
    
    print("Testing POST /api/runs/{run_id}/resolve...")
    
    resolution = {
        "action": "abandon"  # Safe test - just abandon the task
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/runs/{run_id}/resolve",
            json=resolution
        )
        data = response.json()
        print(f"✅ Response: {json.dumps(data, indent=2)}\n")
        print("   Successfully sent resolution!")
        
    except Exception as e:
        print(f"❌ Error sending resolution: {e}\n")


if __name__ == "__main__":
    test_interrupt_endpoints()
