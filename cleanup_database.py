"""
Database Cleanup Script
=======================
Your 2GB database is causing silent crashes. This script will:
1. Archive old run data to a backup file
2. Keep only recent runs in the main database
3. Vacuum the database to reclaim space

SAFE: Creates backup before any deletes.
"""

import sqlite3
import shutil
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "orchestrator.db"
BACKUP_DIR = Path(__file__).parent / "db_backups"
KEEP_RUNS_DAYS = 3  # Keep runs from last 7 days

def main():
    print("=" * 60)
    print("DATABASE CLEANUP SCRIPT")
    print("=" * 60)
    
    # Check database size
    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nCurrent database size: {db_size_mb:.1f} MB")
    
    if db_size_mb < 500:
        print("✓ Database size is acceptable (< 500MB)")
        print("  Crash may be from another cause")
        return
    
    # Create backup directory
    BACKUP_DIR.mkdir(exist_ok=True)
    
    # Backup current database
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"orchestrator_backup_{timestamp}.db"
    
    print(f"\n1. Creating backup...")
    print(f"   {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print("   ✓ Backup created")
    
    # Connect and clean up
    print(f"\n2. Cleaning up old data...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get cutoff date
    cutoff_date = (datetime.now() - timedelta(days=KEEP_RUNS_DAYS)).isoformat()
    
    # Count runs to delete
    cursor.execute("SELECT COUNT(*) FROM runs WHERE created_at < ?", (cutoff_date,))
    delete_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM runs")
    total_count = cursor.fetchone()[0]
    
    print(f"   Total runs: {total_count}")
    print(f"   Runs older than {KEEP_RUNS_DAYS} days: {delete_count}")
    print(f"   Keeping: {total_count - delete_count}")
    
    if delete_count == 0:
        print("   ✓ No old data to delete")
    else:
        # Get thread_ids of runs to delete
        cursor.execute("SELECT thread_id FROM runs WHERE created_at < ?", (cutoff_date,))
        old_thread_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete old runs
        cursor.execute("DELETE FROM runs WHERE created_at < ?", (cutoff_date,))
        
        # Delete old checkpoints (LangGraph checkpoint table)
        # Checkpoints use thread_id, not thread_ts
        if old_thread_ids:
            placeholders = ','.join('?' * len(old_thread_ids))
            cursor.execute(f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})", old_thread_ids)
        
        conn.commit()
        print(f"   ✓ Deleted {delete_count} old runs")
    
    # Vacuum database
    print(f"\n3. Vacuuming database...")
    cursor.execute("VACUUM")
    conn.close()
    
    new_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    saved_mb = db_size_mb - new_size_mb
    
    print(f"   ✓ Vacuum complete")
    print(f"\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)
    print(f"Original size: {db_size_mb:.1f} MB")
    print(f"New size:      {new_size_mb:.1f} MB")
    print(f"Saved:         {saved_mb:.1f} MB ({saved_mb/db_size_mb*100:.1f}%)")
    print(f"\nBackup saved to: {backup_path}")
    
    if new_size_mb > 500:
        print("\n⚠️  WARNING: Database still > 500MB")
        print("   Consider reducing KEEP_RUNS_DAYS or deleting more data")
    else:
        print("\n✓ Database size is now acceptable")
        print("  Restart the server and monitor for crashes")

if __name__ == "__main__":
    main()
