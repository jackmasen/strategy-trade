"""
服务重启辅助脚本
独立运行，负责等待主进程退出后重新启动服务

用法：
    python service_restarter.py <main_script_path> <wait_seconds>
"""
import sys
import time
import subprocess
import os
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print("Usage: service_restarter.py <main_script_path> <wait_seconds>")
        sys.exit(1)

    main_script = Path(sys.argv[1])
    wait_seconds = float(sys.argv[2])

    if not main_script.exists():
        print(f"Error: Main script not found: {main_script}")
        sys.exit(1)

    # 等待指定时间，让主进程有时间退出并释放端口
    print(f"[Restarter] Waiting {wait_seconds}s for main process to exit...")
    time.sleep(wait_seconds)

    # 启动新的主进程
    python_exe = sys.executable
    cwd = str(main_script.parent)
    env = os.environ.copy()

    print(f"[Restarter] Starting new process: {python_exe} {main_script}")
    print(f"[Restarter] Working directory: {cwd}")

    try:
        if sys.platform == "win32":
            # Windows: 分离进程
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                [python_exe, str(main_script)],
                cwd=cwd,
                env=env,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            )
        else:
            # Linux/macOS: 新会话
            subprocess.Popen(
                [python_exe, str(main_script)],
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
        print("[Restarter] New process started successfully")
    except Exception as e:
        print(f"[Restarter] Failed to start new process: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
