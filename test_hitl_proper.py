"""
Proper HITL Test - Creates and RUNS a failing task
====================================================

This script:
1. Creates a run via the API (sets it to running)
2. The run has an impossible objective that will fail
3. After 4 failures, it triggers HITL
4. You can test the InterruptModal in the dashboard

Usage:
    python test_hitl_proper.py
"""

import requests
import json
import time

BASE_URL = "http://localhost:8085"

def main():
    print("="*70)
    print("HITL Test - Creating Failing Run")
    print("="*70)
    
    # Check server
    try:
        requests.get(f"{BASE_URL}/api/runs")
        print("✅ Server is running\n")
    except:
        print("❌ Server not running!")
        print("   Start with: python src/server.py")
        return
    
    # Create impossible objective that will fail fast
    objective = """
Create a Python file called test.py that imports a non-existent module:

import impossible_fake_module_that_does_not_exist_xyz_12345

This will fail immediately and retry until HITL triggers.
    """.strip()
    
    print("Creating run with failing objective...")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/runs",
            json={
                "objective": objective,
                "spec": {}
            }
        )
        
        if response.status_code != 200:
            print(f"❌ Error {response.status_code}: {response.text}")
            return
            
        data = response.json()
        run_id = data["run_id"]
        
        print(f"✅ Run created: {run_id}")
        print(f"   Status: running (director will process it)")
        print()
        print("="*70)
        print("WHAT HAPPENS NEXT:")
        print("="*70)
        print("\n1. Director creates tasks")
        print("2. Worker tries to import fake module → FAILS")
        print("3. Phoenix retries → FAILS again (x4 total)")
        print("4. After 4th failure → Calls interrupt()")
        print("5. Task status → WAITING_HUMAN")
        print("6. Dashboard polling detects interrupt")
        print("7. InterruptModal appears!")
        print("\n" + "="*70)
        print("CHECK THE DASHBOARD:")
        print("="*70)
        print(f"\n🌐 http://localhost:3000")
        print(f"\n   Look for run: {run_id}")
        print(f"   Wait for modal to appear (may take 1-2 min)")
        print("\n" + "="*70)
        
        # Monitor
        print("\nMonitoring for interrupt (Ctrl+C to stop)...\n")
        monitor_run(run_id)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def monitor_run(run_id: str):
    """Poll for interrupt."""
    
    check_count = 0
    last_status = None
    
    try:
        while True:
            time.sleep(5)
            check_count += 1
            
            try:
                # Check run status
                run_resp = requests.get(f"{BASE_URL}/api/runs/{run_id}")
                run_data = run_resp.json()
                status = run_data.get("strategy_status", "unknown")
                
                if status != last_status:
                    print(f"[{time.strftime('%H:%M:%S')}] Run status: {status}")
                    last_status = status
                
                # Check tasks
                tasks = run_data.get("tasks", [])
                if tasks:
                    for task in tasks:
                        task_status = task.get("status")
                        task_id = task.get("id", "unknown")[:12]
                        
                        if task_status == "waiting_human":
                            print(f"\n{'='*70}")
                            print("🎯 TASK IS WAITING FOR HUMAN!")
                            print(f"{'='*70}")
                            print(f"Task: {task_id}")
                            print(f"Status: waiting_human")
                            print(f"\nNow checking for interrupt...")
                
                # Check for interrupt
                int_resp = requests.get(f"{BASE_URL}/api/runs/{run_id}/interrupts")
                int_data = int_resp.json()
                
                if int_data.get("interrupted"):
                    print(f"\n{'='*70}")
                    print("✅ INTERRUPT DETECTED!")
                    print(f"{'='*70}")
                    interrupt_info = int_data.get("data", {})
                    print(f"\nTask: {interrupt_info.get('task_id')}")
                    print(f"Component: {interrupt_info.get('component')}")
                    print(f"Retry Count: {interrupt_info.get('retry_count')}")
                    print(f"\nFailure:")
                    print(f"  {interrupt_info.get('failure_reason', 'Unknown')[:150]}")
                    print(f"\n{'='*70}")
                    print("🎨 OPEN THE DASHBOARD NOW!")
                    print(f"{'='*70}")
                    print(f"\n   http://localhost:3000")
                    print(f"\n   The InterruptModal should be showing")
                    print(f"   Test all 3 resolution options!")
                    print(f"\n{'='*70}")
                    break
                else:
                    if check_count % 3 == 0:  # Every 15 seconds
                        print(f"[Check {check_count}] No interrupt yet... still processing")
                    
            except Exception as e:
                print(f"[Check {check_count}] Error: {e}")
                
            if check_count > 40:  # 200 seconds = ~3 minutes
                print("\n⏱️  Timeout - task may be taking longer than expected")
                print(f"   Check manually:")
                print(f"   curl {BASE_URL}/api/runs/{run_id}/interrupts")
                break
                
    except KeyboardInterrupt:
        print(f"\n\n✋ Stopped monitoring")
        print(f"   Dashboard: http://localhost:3000 (run {run_id})")


if __name__ == "__main__":
    main()
