#!/bin/bash
# 从 AWS S3 公开镜像并发下载 EEGMAT 数据集
set -u
BASE="https://physionet-open.s3.amazonaws.com/eegmat/1.0.0"
DEST="eeg-focus/data/eegmat"
mkdir -p "$DEST"

# 生成 (文件名 完整URL) 成对列表
LIST="$(dirname "$0")/urls.txt"
: > "$LIST"
for f in README.txt RECORDS SHA256SUMS.txt subject-info.csv; do
  echo "$f $BASE/$f" >> "$LIST"
done
for i in $(seq -w 0 35); do
  for s in 1 2; do
    fn="Subject${i}_${s}.edf"
    echo "$fn $BASE/$fn" >> "$LIST"
  done
done

# 8 路并发下载
xargs -P 8 -n 2 curl -sL --retry 3 -o < "$LIST"
echo "DONE"
