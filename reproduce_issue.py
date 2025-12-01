
import os
import sys
import shutil
from src.tools.code_execution import run_shell

def test_run_shell_unittest():
    # Setup a test directory
    test_dir = os.path.abspath("temp_test_env")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir)

    # Create a dummy test file
    test_file_content = """
import unittest

class TestDummy(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(1, 1)

if __name__ == '__main__':
    unittest.main()
"""
    with open(os.path.join(test_dir, "test_dummy.py"), "w") as f:
        f.write(test_file_content)

    # Create __init__.py
    with open(os.path.join(test_dir, "__init__.py"), "w") as f:
        f.write("")

    print(f"Created test environment at: {test_dir}")
    
    # Test 1: Run with CWD and .py extension
    print("\n--- Test 1: Run with CWD and .py extension ---")
    output = run_shell("python -m unittest test_dummy.py", cwd=test_dir)
    print(output)

    # Test 2: Run with CWD and NO extension
    print("\n--- Test 2: Run with CWD and NO extension ---")
    output = run_shell("python -m unittest test_dummy", cwd=test_dir)
    print(output)

    # Cleanup
    # shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_run_shell_unittest()
