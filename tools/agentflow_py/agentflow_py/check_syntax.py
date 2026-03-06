"""语法检查脚本"""
import ast
import sys

def check_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        ast.parse(content)
        print(f"[OK] {path} 语法检查通过")
        return True
    except SyntaxError as e:
        print(f"[FAIL] {path} 语法错误: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] {path} 错误: {e}")
        return False

if __name__ == "__main__":
    files = [
        "main.py",
        "agentflow/storage/redis_client.py",
        "agentflow/namespace/manager.py",
        "agentflow/namespace/tools.py",
    ]
    
    all_ok = True
    for f in files:
        if not check_file(f):
            all_ok = False
    
    sys.exit(0 if all_ok else 1)
