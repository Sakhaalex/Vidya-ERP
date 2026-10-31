"""
Vidya ERP - Automated Test Runner
Discovers and executes unit, integration, and contract tests for the Data Engine.
"""
import os
import sys
import unittest

def main():
    # Ensure workspace root is in sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    print("=" * 70)
    print("VIDYA DATA ENGINE - AUTOMATED TEST SUITE")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(root_dir, "tests"), pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)

    if not result.wasSuccessful():
        sys.exit(1)

if __name__ == "__main__":
    main()
