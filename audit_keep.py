import os
import ast

for root, dirs, files in os.walk('.'):
    # skip .venv
    if '.venv' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'rb') as f:
                    ast.parse(f.read())
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")
