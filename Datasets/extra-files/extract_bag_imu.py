"""Pure-Python rosbag IMU extractor (ROS1 and ROS2) using `rosbags` lib.

Drop-in replacement for `extract-rosbag-imu` / `extract-ros2bag-imu`.
Works on any platform — no ROS system packages required.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from rosbags.rosbag1 import Reader as Ros1Reader
from rosbags.rosbag2 import Reader as Ros2Reader
from rosbags.typesys import Stores, get_typestore


def _open_bag(bag_path: Path):
    p = Path(bag_path)
    if p.is_file() and p.suffix == ".bag":
        return Ros1Reader(p), get_typestore(Stores.ROS1_NOETIC)
    if p.is_dir() or p.suffix in {".db3", ".mcap"}:
        return Ros2Reader(p), get_typestore(Stores.ROS2_HUMBLE)
    raise ValueError(f"Cannot determine bag format for: {bag_path}")


def _stamp_to_ns(stamp) -> int | None:
    if stamp is None:
        return None
    secs = getattr(stamp, "sec", None)
    if secs is None:
        secs = getattr(stamp, "secs", None)
    nsec = getattr(stamp, "nanosec", None)
    if nsec is None:
        nsec = getattr(stamp, "nsecs", None)
    if secs is None or nsec is None:
        return None
    return int(secs) * 1_000_000_000 + int(nsec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rosbag_path", required=True)
    ap.add_argument("--sequence_path", required=True)
    ap.add_argument("--imu_topic", required=True)
    ap.add_argument("--imu_name", default="0")
    args = ap.parse_args()

    bag_path = Path(args.rosbag_path)
    sequence_path = Path(args.sequence_path)
    imu_csv = sequence_path / f"imu_{args.imu_name}.csv"

    reader_cm, typestore = _open_bag(bag_path)

    rows: list[dict] = []
    with reader_cm as reader:
        conns = [c for c in reader.connections if c.topic == args.imu_topic]
        if not conns:
            topics = sorted({c.topic for c in reader.connections})
            print(f"ERROR: topic {args.imu_topic!r} not in bag. Present: {topics}", file=sys.stderr)
            return 2

        total = sum(c.msgcount for c in conns)
        desc = f"Extracting IMU from {args.imu_topic}"
        for conn, t, raw in tqdm(reader.messages(connections=conns), total=total, desc=desc):
            try:
                msg = typestore.deserialize_ros1(raw, conn.msgtype) if isinstance(reader, Ros1Reader) else typestore.deserialize_cdr(raw, conn.msgtype)
            except Exception as e:
                print(f"deserialize failed at t={t}: {e}", file=sys.stderr)
                continue

            hdr_stamp = getattr(getattr(msg, "header", None), "stamp", None)
            ts_ns = _stamp_to_ns(hdr_stamp)
            if ts_ns is None:
                ts_ns = int(t)

            rows.append({
                "ts (ns)": ts_ns,
                "wx (rad s^-1)": msg.angular_velocity.x,
                "wy (rad s^-1)": msg.angular_velocity.y,
                "wz (rad s^-1)": msg.angular_velocity.z,
                "ax (m s^-2)": msg.linear_acceleration.x,
                "ay (m s^-2)": msg.linear_acceleration.y,
                "az (m s^-2)": msg.linear_acceleration.z,
            })

    out = pd.DataFrame(rows, columns=[
        "ts (ns)", "wx (rad s^-1)", "wy (rad s^-1)", "wz (rad s^-1)",
        "ax (m s^-2)", "ay (m s^-2)", "az (m s^-2)",
    ])
    tmp = imu_csv.with_name(f"{imu_csv.name}.tmp")
    try:
        out.to_csv(tmp, index=False)
        tmp.replace(imu_csv)
    finally:
        if tmp.exists():
            tmp.unlink()

    print(f"Wrote {len(out)} IMU messages to {imu_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
