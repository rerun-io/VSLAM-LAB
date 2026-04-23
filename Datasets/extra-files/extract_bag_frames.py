"""Pure-Python rosbag frame extractor (ROS1 and ROS2) using `rosbags` lib.

Drop-in replacement for `extract-rosbag-frames` / `extract-ros2bag-frames`.
Works on any platform — no ROS system packages required. Intended for
aarch64 where the pixi `ros1`/`ros2` features are unavailable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from tqdm import tqdm

from rosbags.rosbag1 import Reader as Ros1Reader
from rosbags.rosbag2 import Reader as Ros2Reader
from rosbags.typesys import Stores, get_typestore


_CV_CODES = {
    "mono8": (np.uint8, 1, None),
    "8UC1": (np.uint8, 1, None),
    "mono16": (np.uint16, 1, None),
    "16UC1": (np.uint16, 1, None),
    "bgr8": (np.uint8, 3, None),
    "rgb8": (np.uint8, 3, cv2.COLOR_RGB2BGR),
    "bgra8": (np.uint8, 4, None),
    "rgba8": (np.uint8, 4, cv2.COLOR_RGBA2BGRA),
    "bayer_rggb8": (np.uint8, 1, cv2.COLOR_BayerRG2BGR),
    "bayer_bggr8": (np.uint8, 1, cv2.COLOR_BayerBG2BGR),
    "bayer_gbrg8": (np.uint8, 1, cv2.COLOR_BayerGB2BGR),
    "bayer_grbg8": (np.uint8, 1, cv2.COLOR_BayerGR2BGR),
}


def _image_to_bgr(msg) -> np.ndarray:
    enc = msg.encoding
    if enc not in _CV_CODES:
        raise ValueError(f"Unsupported image encoding: {enc!r}")

    dtype, channels, convert = _CV_CODES[enc]
    data = np.frombuffer(bytes(msg.data), dtype=dtype)
    if channels == 1:
        img = data.reshape(msg.height, msg.width)
    else:
        img = data.reshape(msg.height, msg.width, channels)

    if convert is not None:
        img = cv2.cvtColor(img, convert)
    return img


def _compressed_to_bgr(msg) -> np.ndarray:
    arr = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("cv2.imdecode returned None for CompressedImage")
    return img


def _open_bag(bag_path: Path):
    """Return (reader_cm, typestore) — detects ros1 vs ros2."""
    p = Path(bag_path)
    if p.is_file() and p.suffix == ".bag":
        return Ros1Reader(p), get_typestore(Stores.ROS1_NOETIC)
    # ros2: either .db3 sibling or a directory containing metadata.yaml
    if p.is_dir() or p.suffix in {".db3", ".mcap"}:
        return Ros2Reader(p), get_typestore(Stores.ROS2_HUMBLE)
    raise ValueError(f"Cannot determine bag format for: {bag_path}")


def _stamp_to_ns(stamp) -> int | None:
    if stamp is None:
        return None
    # ros1 Header has stamp.secs / stamp.nsecs; ros2 has stamp.sec / stamp.nanosec.
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
    ap.add_argument("--image_topic", required=True)
    ap.add_argument("--cam", required=True)
    args = ap.parse_args()

    bag_path = Path(args.rosbag_path)
    sequence_path = Path(args.sequence_path)
    rgb_path = sequence_path / f"rgb_{args.cam}"
    rgb_path.mkdir(parents=True, exist_ok=True)

    reader_cm, typestore = _open_bag(bag_path)

    rgb_files: list[str] = []
    ts_list: list[int] = []

    with reader_cm as reader:
        conns = [c for c in reader.connections if c.topic == args.image_topic]
        if not conns:
            topics = sorted({c.topic for c in reader.connections})
            print(f"ERROR: topic {args.image_topic!r} not in bag. Present: {topics}", file=sys.stderr)
            return 2

        msgtype = conns[0].msgtype
        total = sum(c.msgcount for c in conns)
        desc = f"Extracting frames from {args.image_topic} ({msgtype})"

        for conn, t, raw in tqdm(reader.messages(connections=conns), total=total, desc=desc):
            try:
                msg = typestore.deserialize_ros1(raw, conn.msgtype) if isinstance(reader, Ros1Reader) else typestore.deserialize_cdr(raw, conn.msgtype)
            except Exception as e:
                print(f"deserialize failed at t={t}: {e}", file=sys.stderr)
                continue

            try:
                if "CompressedImage" in conn.msgtype:
                    img = _compressed_to_bgr(msg)
                else:
                    img = _image_to_bgr(msg)
            except Exception as e:
                print(f"decode failed at t={t}: {e}", file=sys.stderr)
                continue

            hdr_stamp = getattr(getattr(msg, "header", None), "stamp", None)
            ts_ns = _stamp_to_ns(hdr_stamp)
            if ts_ns is None:
                ts_ns = int(t)

            image_name = f"{ts_ns}.png"
            cv2.imwrite(str(rgb_path / image_name), img)
            rgb_files.append(f"rgb_{args.cam}/{image_name}")
            ts_list.append(ts_ns)

    # Write / merge rgb.csv side-by-side with other cams if already present.
    rgb_csv = sequence_path / "rgb.csv"
    ts_col = f"ts_rgb_{args.cam} (ns)"
    path_col = f"path_rgb_{args.cam}"
    new_rgb = pd.DataFrame({ts_col: pd.Series(ts_list, dtype="int64"), path_col: rgb_files})

    if rgb_csv.exists():
        existing = pd.read_csv(rgb_csv)
        overlap = [c for c in new_rgb.columns if c in existing.columns]
        if overlap:
            raise ValueError(f"Columns already exist in {rgb_csv}: {overlap}")
        out = existing.join(new_rgb, how="outer")
    else:
        out = new_rgb

    out[ts_col] = out[ts_col].astype("Int64")
    tmp = rgb_csv.with_name(f"{rgb_csv.name}.tmp")
    try:
        out.to_csv(tmp, index=False)
        tmp.replace(rgb_csv)
    finally:
        if tmp.exists():
            tmp.unlink()

    print(f"Wrote {len(new_rgb)} frames to {rgb_path} and updated {rgb_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
