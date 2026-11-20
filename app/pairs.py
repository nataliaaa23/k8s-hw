import argparse
import csv
import hashlib
import io
import json
import os
import re
import resource
import sys
import time
from collections import Counter
from itertools import combinations

import boto3

ENDPOINT = os.environ.get("S3_ENDPOINT", "http://host.docker.internal:9100")
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "rustfsadmin")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "rustfsadmin")
BUCKET = os.environ.get("S3_BUCKET", "hh-lake")
CSV_KEY = os.environ.get("CSV_KEY", "raw/it_vacancies_2024.csv")
PREFIX = os.environ.get("RESULT_PREFIX", "results/k8s")

ROLE = "Программист, разработчик"
NAME_RE = re.compile(r"(^|[^0-9])1\s?[cс]")
CHUNK = 8 * 1024 * 1024
HEADER_BYTES = 64 * 1024

csv.field_size_limit(sys.maxsize)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def s3_client():
    return boto3.client("s3", endpoint_url=ENDPOINT, aws_access_key_id=ACCESS_KEY,
                        aws_secret_access_key=SECRET_KEY, region_name="us-east-1")


def get_range(s3, start, end):
    return s3.get_object(Bucket=BUCKET, Key=CSV_KEY, Range=f"bytes={start}-{end}")["Body"].read()


def object_size(s3):
    return s3.head_object(Bucket=BUCKET, Key=CSV_KEY)["ContentLength"]


def read_columns(s3, size):
    head = get_range(s3, 0, min(HEADER_BYTES, size) - 1).decode("utf-8-sig", errors="ignore")
    line = head[:head.index("\n") + 1]
    header = next(csv.reader(io.StringIO(line, newline="")))
    return {name: i for i, name in enumerate(header)}


def norm_skill(s):
    return s.strip(" ").lower().replace("1c", "1с")


def last_boundary(buf):
    parts = buf.split(b'"')
    offset, cut = 0, 0
    for i, p in enumerate(parts):
        if i % 2 == 0:
            j = p.rfind(b"\n")
            if j != -1:
                cut = offset + j + 1
        offset += len(p) + 1
    return cut


def pieces(s3, start, end):
    pos, carry, first = start, b"", True
    while pos < end:
        stop = min(pos + CHUNK, end)
        body = get_range(s3, pos, stop - 1)
        pos = stop
        buf = carry + body
        cut = len(buf) if pos >= end else last_boundary(buf)
        if cut == 0:
            carry = buf
            continue
        data, carry = buf[:cut], buf[cut:]
        text = data.decode("utf-8-sig" if start == 0 and first else "utf-8")
        if start == 0 and first:
            text = text[text.index("\n") + 1:]
        first = False
        yield text


def count_text(text, cols, pairs, stat):
    need = max(cols["role"], cols["name"], cols["key_skills"])
    for row in csv.reader(io.StringIO(text, newline="")):
        stat["total"] += 1
        if len(row) <= need:
            stat["bad"] += 1
            continue
        name = row[cols["name"]].lower()
        if row[cols["role"]] != ROLE or not NAME_RE.search(name):
            continue
        if "битрикс" in name or "bitrix" in name:
            continue
        stat["variant"] += 1
        raw = row[cols["key_skills"]]
        if not raw:
            continue
        skills = sorted({norm_skill(s) for s in raw.split(";") if s.strip(" ")})
        if not skills:
            continue
        stat["with_skills"] += 1
        pairs.update(combinations(skills, 2))


def process_range(s3, start, end, cols):
    pairs = Counter()
    stat = dict(total=0, variant=0, with_skills=0, bad=0, chunks=0)
    for text in pieces(s3, start, end):
        count_text(text, cols, pairs, stat)
        stat["chunks"] += 1
    return pairs, stat


def peak_memory():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    cg = None
    for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try:
            with open(path) as f:
                cg = int(f.read().strip()) / 1024 / 1024
            break
        except (OSError, ValueError):
            continue
    return rss, cg


def log_peak():
    rss, cg = peak_memory()
    log(f"пик памяти процесса (ru_maxrss): {rss:.1f} МиБ")
    if cg is not None:
        log(f"пик памяти контейнера (cgroup memory.peak): {cg:.1f} МиБ")


def write_pairs_csv(counter, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["skills", "count"])
        for key, cnt in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
            w.writerow([" || ".join(key), cnt])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def report_top(counter, path, label):
    write_pairs_csv(counter, path)
    log(f"{label}: уникальных пар {len(counter)}, сумма вхождений {sum(counter.values())}")
    log(f"sha256 файла пар: {sha256_file(path)}")
    log("топ-10 пар навыков:")
    for key, cnt in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        print(f"  {cnt:6d}  {' || '.join(key)}", flush=True)


def upload(s3, local, key):
    s3.upload_file(local, BUCKET, key)
    log(f"загружено в s3://{BUCKET}/{key}")


def cmd_run(args):
    t0 = time.time()
    s3 = s3_client()
    size = object_size(s3)
    cols = read_columns(s3, size)
    log(f"объект {CSV_KEY}: {size} байт, режим одного процесса")
    pairs, stat = process_range(s3, 0, size, cols)
    log(f"записей {stat['total']}, вакансий варианта {stat['variant']}, с навыками {stat['with_skills']}, битых строк {stat['bad']}, чанков {stat['chunks']}")
    out = "/tmp/skills_2.csv"
    report_top(pairs, out, "результат")
    log(f"время расчёта: {time.time() - t0:.1f} с")
    log_peak()
    if args.upload:
        upload(s3, out, f"{PREFIX}/single/skills_2.csv")


def cmd_plan(args):
    t0 = time.time()
    s3 = s3_client()
    size = object_size(s3)
    parts = args.parts
    targets = [size * i // parts for i in range(1, parts)]
    bounds, ti, pos, parity = [0], 0, 0, 0
    while pos < size and ti < len(targets):
        stop = min(pos + CHUNK, size)
        body = get_range(s3, pos, stop - 1)
        off = 0
        for i, p in enumerate(body.split(b'"')):
            base = pos + off
            if (parity + i) % 2 == 0:
                while ti < len(targets):
                    j = p.find(b"\n", max(0, targets[ti] - 1 - base))
                    if j == -1:
                        break
                    bounds.append(base + j + 1)
                    ti += 1
            off += len(p) + 1
        parity = (parity + body.count(b'"')) % 2
        pos = stop
    while len(bounds) < parts:
        bounds.append(size)
    bounds.append(size)
    ranges = [[bounds[i], bounds[i + 1]] for i in range(parts)]
    plan = dict(size=size, parts=parts, ranges=ranges)
    path = "/tmp/plan.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f)
    for i, (a, b) in enumerate(ranges):
        log(f"часть {i}: байты {a}..{b}, размер {b - a}")
    upload(s3, path, f"{PREFIX}/plan.json")
    log(f"время планирования: {time.time() - t0:.1f} с")
    log_peak()


def cmd_part(args):
    t0 = time.time()
    index = args.index if args.index is not None else int(os.environ["JOB_COMPLETION_INDEX"])
    s3 = s3_client()
    plan = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}/plan.json")["Body"].read())
    a, b = plan["ranges"][index]
    cols = read_columns(s3, plan["size"])
    log(f"часть {index} из {plan['parts']}: байты {a}..{b}")
    pairs, stat = process_range(s3, a, b, cols)
    log(f"записей {stat['total']}, вакансий варианта {stat['variant']}, с навыками {stat['with_skills']}, битых строк {stat['bad']}, чанков {stat['chunks']}")
    out = f"/tmp/part-{index}.json"
    data = dict(index=index, stat=stat, pairs=[[" || ".join(k), v] for k, v in pairs.items()])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    upload(s3, out, f"{PREFIX}/parts/part-{index}.json")
    log(f"время части: {time.time() - t0:.1f} с")
    log_peak()


def cmd_merge(args):
    t0 = time.time()
    s3 = s3_client()
    total = Counter()
    stat = dict(total=0, variant=0, with_skills=0, bad=0, chunks=0)
    for i in range(args.parts):
        data = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}/parts/part-{i}.json")["Body"].read())
        for k, v in data["pairs"]:
            total[tuple(k.split(" || "))] += v
        for name in stat:
            stat[name] += data["stat"][name]
        log(f"часть {i} учтена: записей {data['stat']['total']}, с навыками {data['stat']['with_skills']}")
    log(f"всего записей {stat['total']}, вакансий варианта {stat['variant']}, с навыками {stat['with_skills']}, битых строк {stat['bad']}")
    out = "/tmp/skills_2.csv"
    report_top(total, out, "итог по частям")
    upload(s3, out, f"{PREFIX}/skills_2.csv")
    log(f"время слияния: {time.time() - t0:.1f} с")
    log_peak()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--upload", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("plan")
    p.add_argument("--parts", type=int, required=True)
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("part")
    p.add_argument("--index", type=int)
    p.set_defaults(fn=cmd_part)
    p = sub.add_parser("merge")
    p.add_argument("--parts", type=int, required=True)
    p.set_defaults(fn=cmd_merge)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
