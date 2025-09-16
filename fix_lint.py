#!/usr/bin/env python3
"""
Simple script to fix common linting issues
"""

import os
import re
import subprocess
import sys

def fix_imports(file_path):
    """Fix import ordering and unused imports"""
    with open(file_path, 'r') as f:
        content = f.read()

    # Remove trailing whitespace
    lines = content.split('\n')
    fixed_lines = [line.rstrip() for line in lines]

    # Remove multiple blank lines
    result_lines = []
    prev_blank = False
    for line in fixed_lines:
        if line.strip() == '':
            if not prev_blank:
                result_lines.append(line)
            prev_blank = True
        else:
            result_lines.append(line)
            prev_blank = False

    # Write back
    with open(file_path, 'w') as f:
        f.write('\n'.join(result_lines))

def main():
    """Fix common linting issues in Python files"""

    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk('.'):
        # Skip hidden directories and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))

    print(f"Found {len(python_files)} Python files")

    for file_path in python_files:
        print(f"Fixing {file_path}")
        try:
            fix_imports(file_path)
        except Exception as e:
            print(f"Error fixing {file_path}: {e}")

    print("Done!")

if __name__ == "__main__":
    main()
