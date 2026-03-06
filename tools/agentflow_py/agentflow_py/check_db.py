import sqlite3
import os
import glob
import urllib.request
import json

# 搜索所有可能的数据库路径
search_dirs = [
    r"C:\agentflow",
    r"C:\agentflow\agentflow_py",
    r"C:\agentflow\agentflow_py\data",
    r"C:\agentflow\data",
]

print("=== 搜索数据库文件 ===")
for d in search_dirs:
    if os.path.exists(d):
        print(f"\n目录存在: {d}")
        for f in os.listdir(d):
            print(f"  {f}")
    else:
        print(f"目录不存在: {d}")

# 用glob搜索
print("\n=== glob搜索 *.db ===")
for p in glob.glob(r"C:\agentflow\**\*.db", recursive=True):
    size = os.path.getsize(p)
    print(f"  {p} ({size} bytes)")

for p in paths:
    if os.path.exists(p):
        print(f"\n=== 找到数据库: {p} ===")
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        
        # 查看各表数量
        for tbl in ("kv_store", "hash_store", "zset_store", "set_store", "stream_store"):
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            print(f"  {tbl}: {cur.fetchone()[0]} 条")
        
        # 查看zset_store中的key
        cur.execute("SELECT DISTINCT key FROM zset_store LIMIT 30")
        rows = cur.fetchall()
        print(f"\n  zset keys ({len(rows)}):")
        for r in rows:
            print(f"    {r[0]}")
        
        # 查看set_store中的key
        cur.execute("SELECT DISTINCT key FROM set_store LIMIT 20")
        rows = cur.fetchall()
        print(f"\n  set keys ({len(rows)}):")
        for r in rows:
            print(f"    {r[0]}")
        
        # 查看stream_store中的key
        cur.execute("SELECT DISTINCT key FROM stream_store LIMIT 20")
        rows = cur.fetchall()
        print(f"\n  stream keys ({len(rows)}):")
        for r in rows:
            print(f"    {r[0]}")
        
        conn.close()
    else:
        print(f"不存在: {p}")

try:
    with urllib.request.urlopen("http://localhost:8081/api/dashboard", timeout=5) as resp:
        data = json.loads(resp.read())
        print("=== /api/dashboard ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"请求失败: {e}")

try:
    with urllib.request.urlopen("http://localhost:8081/api/tasks", timeout=5) as resp:
        data = json.loads(resp.read())
        print("\n=== /api/tasks ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"请求失败: {e}")