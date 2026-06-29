"""Hourly monitor for the closed-loop run: stats + auto-resume on death.

- prints member statistics (count by iter, rate, ETA, misfit checkpoints)
- if the run is dead AND not complete: frees orphan tNavigator-con licenses,
  then relaunches DETACHED (survives this process), resuming from the archive.
- never starts a second copy while one is alive.
"""
import glob
import os
import subprocess
import sys
from datetime import datetime

OUT = "outputs/closed_loop"
CMD = [sys.executable, "-m", "cmp_ensemble.cli", "closed-loop",
       "--cluster", "0", "--N", "75", "--n-alpha", "4",
       "--skip-final-eval", "--execute", "--out", OUT]
TARGET = 300


def _ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                          capture_output=True, text=True).stdout.strip()


def alive():
    n = _ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' "
            "-and $_.CommandLine -match 'closed-loop' } | Measure-Object | "
            "Select-Object -ExpandProperty Count")
    try:
        return int(n) > 0
    except ValueError:
        return False


def complete():
    return os.path.exists(f"{OUT}/Theta_post.npy")


def kill_orphan_con():
    _ps("Get-Process -Name 'tNavigator-con-v26.1-4207-g254db398cdfc' "
        "-ErrorAction SilentlyContinue | Stop-Process -Force")


def kill_stray_closed_loop():
    """Kill any lingering closed-loop python (zombie from a dead wrapper) so we
    never end up with two copies fighting over the slot/license."""
    _ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' "
        "-and $_.CommandLine -match 'closed-loop' } | ForEach-Object "
        "{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def relaunch():
    import time
    kill_stray_closed_loop()   # defensive: never run two copies
    kill_orphan_con()
    time.sleep(2)
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    log = open("logs/cl_real.log", "ab")
    subprocess.Popen(CMD, stdout=log, stderr=log, close_fds=True,
                     creationflags=DETACHED)


def stats():
    print("=" * 54)
    print("CLOSED-LOOP MONITOR @", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 54)
    members = sorted(glob.glob(f"{OUT}/iter_*/member_*/d_sim.npy"))
    by_iter = {}
    for m in members:
        it = m.split("iter_")[1].split(os.sep)[0]
        by_iter[it] = by_iter.get(it, 0) + 1
    print(f"members computed: {len(members)}/{TARGET}")
    for it in sorted(by_iter):
        print(f"   iter {it}: {by_iter[it]}/75")
    if len(members) > 1:
        mts = sorted(os.path.getmtime(m) for m in members)
        rate = (mts[-1] - mts[0]) / (len(members) - 1)
        if rate > 0:
            rem = TARGET - len(members)
            print(f"avg/member: {rate/60:.1f} min | last: "
                  f"{datetime.fromtimestamp(mts[-1]).strftime('%H:%M:%S')} | "
                  f"ETA ~{rem*rate/3600:.1f} h ({rem} left)")
    for ck in sorted(glob.glob(f"{OUT}/iter_*/meta.yaml")):
        body = open(ck, encoding="utf-8").read()
        mis = body.split("misfit:")[1].split("\n")[0].strip() if "misfit:" in body else "?"
        print(f"checkpoint {ck.split(os.sep)[-2]}: misfit={mis}")


if __name__ == "__main__":
    stats()
    if complete():
        print("STATUS: RUN COMPLETE (Theta_post.npy exists)")
    elif alive():
        print("STATUS: running")
    else:
        print("STATUS: DEAD -> resuming (detached, from archive)")
        relaunch()
        print("relaunched.")
