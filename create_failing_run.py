"""
HITL Test - Simple API Approach
================================

Creates a run that will fail and trigger HITL.
No complex imports needed - just requests!

Usage:
    .venv\Scripts\python.exe create_failing_run.py
    OR
    python create_failing_run.py (if venv is activated)
"""

import requests
import json
import time

BASE_URL = "http://localhost:8085"

def create_failing_run():
    """Create a run with an impossible objective that will fail."""
    
    print("="*70)
    print("HITL Test - Creating Failing Run")
    print("="*70)
    
    # Check server
    try:
        requests.get(f"{BASE_URL}/api/runs")
        print("✅ Server is running\n")
    except:
        print("❌ Server not running!")
        print("   Start with: .venv\\Scripts\\python.exe src\\server.py")
        return
    
    # Create impossible objective
    objective = """
    Create a Python file called impossible_test.py with this code:
    
    import nonexistent_fake_module_xyz_12345
    
    The file must import this module and use it.
    This will fail because the module doesn't exist.
    """
    
    print("Creating run with impossible objective...")
    print("(This will fail ~4 times, then trigger HITL)\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/runs",
            json={
                "objective": objective.strip(),
                "spec": {}
            }
        )
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return
            
        data = response.json()
        run_id = data["run_id"]
        
        print(f"✅ Run created: {run_id}\n")
        print("="*70)
        print("TESTING INSTRUCTIONS")
        print("="*70)
        print(f"\n1. Open: http://localhost:3000")
        print(f"\n2. Find run: {run_id}")
        print(f"\n3. Watch it fail (server logs will show retries)")
        print(f"\n4. After 4 failures, you'll see:")
        print(f"   - Server log: 'requesting human intervention'")
        print(f"   - Dashboard: InterruptModal appears")
        print(f"\n5. Test resolution actions:")
        print(f"   ✓ Retry with modifications")
        print(f"   ✓ Spawn new task")  
        print(f"   ✓ Abandon")
        print("\n" + "="*70)
        
        # Start monitoring
        print("\nMonitoring for interrupt (Ctrl+C to stop)...\n")
        monitor_run(run_id)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def monitor_run(run_id: str):
    """Poll for interrupt."""
    
    check_count = 0
    
    try:
        while True:
            time.sleep(5)  # Check every 5 seconds
            check_count += 1
            
            try:
                response = requests.get(f"{BASE_URL}/api/runs/{run_id}/interrupts")
                data = response.json()
                
                if data.get("interrupted"):
                    print("\n" + "="*70)
                    print("🎯 INTERRUPT DETECTED!")
                    print("="*70)
                    interrupt_data = data.get("data", {})
                    print(f"\nTask ID: {interrupt_data.get('task_id')}")
                    print(f"Component: {interrupt_data.get('component')}")
                    print(f"Retry Count: {interrupt_data.get('retry_count')}")
                    print(f"\nFailure Reason:")
                    print(f"  {interrupt_data.get('failure_reason', 'Unknown')[:200]}")
                    print("\n" + "="*70)
                    print("✅ GO TO DASHBOARD NOW!")
                    print(f"   http://localhost:3000")
                    print("\n   The InterruptModal should be visible.")
                    print("   Test all three resolution options!")
                    print("="*70)
                    break
                else:
                    print(f"[Check {check_count}] No interrupt yet... (task may still be running)")
                    
            except Exception as e:
                print(f"[Check {check_count}] Error: {e}")
                
            if check_count > 60:  # Stop after 5 minutes
                print("\n⏱️  Timeout - stopping monitor")
                print(f"   Check manually: curl {BASE_URL}/api/runs/{run_id}/interrupts")
                break
                
    except KeyboardInterrupt:
        print(f"\n\n✋ Stopped monitoring")
        print(f"Check: http://localhost:3000 (run {run_id})")


if __name__ == "__main__":
    create_failing_run()
