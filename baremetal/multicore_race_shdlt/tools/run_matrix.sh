#!/bin/bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
test_dir=$(cd "$script_dir/.." && pwd)
repo_root=$test_dir
while [[ ! -f "$repo_root/build.mill" && "$repo_root" != / ]]; do
  repo_root=$(dirname "$repo_root")
done
if [[ ! -f "$repo_root/build.mill" ]]; then
  echo "could not locate VexiiRiscv build.mill above $test_dir" >&2
  exit 2
fi
cpu_count=${1:-2}
shift || true
seed=2
with_rvls=0

while (($#)); do
  case "$1" in
    --seed)
      if (($# < 2)); then
        echo "--seed requires an integer argument" >&2
        exit 2
      fi
      seed=$2
      shift 2
      ;;
    --with-rvls|--rvls-check) with_rvls=1; shift ;;
    --no-rvls|--architecture-only) with_rvls=0; shift ;;
    --help|-h)
      echo "usage: $0 {2|4} [--seed N] [--with-rvls] [case ...]"
      exit 0
      ;;
    --observer|--legacy-observer)
      echo "legacy observer mode is unavailable; use architecture results or --with-rvls" >&2
      exit 2
      ;;
    --) shift; break ;;
    *) break ;;
  esac
done

if [[ "$cpu_count" != 2 && "$cpu_count" != 4 ]]; then
  echo "usage: $0 {2|4} [--seed N] [--with-rvls] [case ...]" >&2
  exit 2
fi
if [[ ! "$seed" =~ ^-?[0-9]+$ ]]; then
  echo "seed must be an integer: $seed" >&2
  exit 2
fi

if (($#)); then
  cases=("$@")
else
  cases=(different_pages order_permute skewed_completion result_isolation \
         buffer_isolation same_page same_pte same_cacheline_ptes)
fi

log_dir="$test_dir/build/logs"
mkdir -p "$log_dir"
cd "$repo_root"

for race_case in "${cases[@]}"; do
  make -C "$test_dir" CPU_COUNT="$cpu_count" CASE="$race_case" compile >/dev/null
  elf="$test_dir/build/cpu${cpu_count}_${race_case}/multicore_race_shdlt.elf"
  log_suffix=""
  if [[ "$seed" != 2 ]]; then
    log_suffix="_seed${seed}"
  fi
  log="$log_dir/cpu${cpu_count}_${race_case}${log_suffix}.log"
  rvls_args=(--no-rvls-check)
  if ((with_rvls)); then rvls_args=(--with-rvls-log); fi
  mill --no-server 'Test[2.13.12].runMain' vexiiriscv.tester.TestBench \
    --xlen 64 --cpu-count "$cpu_count" --reset-vector 0x80000000 \
    --with-isa h,m,a,c,svadu,shdlt,zicntr \
    --with-fetch-l1 --with-lsu-l1 --lsu-l1-coherency \
    --load-elf "$elf" --pass-symbol pass --fail-symbol fail \
    --pass-policy all --fail-policy any --fail-after 300000000 \
    --seed "$seed" \
    "${rvls_args[@]}" \
    --name "shdlt_race_cpu${cpu_count}_${race_case}_seed${seed}" >"$log" 2>&1
  python3 "$script_dir/race_report.py" "$log"
done
