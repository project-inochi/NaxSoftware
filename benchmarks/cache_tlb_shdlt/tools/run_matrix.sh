#!/bin/bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
test_dir=$(cd "$script_dir/.." && pwd)
repo_root=$test_dir
while [[ ! -f "$repo_root/build.mill" && "$repo_root" != / ]]; do repo_root=$(dirname "$repo_root"); done
if [[ ! -f "$repo_root/build.mill" ]]; then echo "could not locate VexiiRiscv build.mill" >&2; exit 2; fi

cpu_arg=${1:-all}
shift || true
profile=baseline
seed_override=
with_rvls=0
while (($#)); do
  case "$1" in
    --profile) profile=${2:?--profile requires a value}; shift 2 ;;
    --seed) seed_override=${2:?--seed requires a value}; shift 2 ;;
    --with-rvls|--rvls-check) with_rvls=1; shift ;;
    --no-rvls|--architecture-only) with_rvls=0; shift ;;
    --help|-h)
      echo "usage: $0 {2|4|all} [--profile baseline|pressure|severe] [--seed N] [--with-rvls] [case ...]"
      exit 0
      ;;
    --observer|--legacy-observer|--ctc-observer)
      echo "legacy CTC observer mode is unavailable; use architecture results or --with-rvls" >&2
      exit 2
      ;;
    --) shift; break ;;
    *) break ;;
  esac
done
case "$cpu_arg" in 2) cpus=(2);; 4) cpus=(4);; all) cpus=(2 4);; *) echo "usage: $0 {2|4|all} [--profile baseline|pressure|severe] [--seed N] [case ...]" >&2; exit 2;; esac

all_cases=(pte_cache_hit_miss remote_pte_reread ownership_transfer coherence_pressure cas_retry \
           hfence_before_after hfence_gpa hfence_vmid hfence_global fence_hart_isolation)
severe_cases=(ownership_transfer coherence_pressure cas_retry fence_hart_isolation)
if (($#)); then cases=("$@"); elif [[ "$profile" == severe ]]; then cases=("${severe_cases[@]}"); else cases=("${all_cases[@]}"); fi

case "$profile" in
  baseline) ready=1.01; latency=0; seeds=(2) ;;
  pressure) ready=0.70; latency=17; seeds=(3 5) ;;
  severe) ready=0.35; latency=53; seeds=(7 11) ;;
  *) echo "unknown profile: $profile" >&2; exit 2 ;;
esac
if [[ -n "$seed_override" ]]; then seeds=("$seed_override"); fi

mode_suffix=
((with_rvls)) && mode_suffix=_rvls
log_dir="$test_dir/build/logs/$profile$mode_suffix"
mkdir -p "$log_dir"
logs=()
cd "$repo_root"
for cpu in "${cpus[@]}"; do
  for ctc_case in "${cases[@]}"; do
    make -C "$test_dir" CPU_COUNT="$cpu" CASE="$ctc_case" compile >/dev/null
    elf="$test_dir/build/cpu${cpu}_${ctc_case}/cache_tlb_shdlt.elf"
    for seed in "${seeds[@]}"; do
      log="$log_dir/cpu${cpu}_${ctc_case}_seed${seed}.log"
      sim_args=(--seed "$seed")
      rvls_args=(--no-rvls-check)
      if ((with_rvls)); then rvls_args=(--with-rvls-log); fi
      mill --no-server 'Test[2.13.12].runMain' vexiiriscv.tester.TestBench \
        --xlen 64 --cpu-count "$cpu" --reset-vector 0x80000000 \
        --with-isa h,m,a,c,svadu,shdlt,zicntr \
        --with-fetch-l1 --with-lsu-l1 --lsu-l1-coherency \
        --load-elf "$elf" --pass-symbol pass --fail-symbol fail \
        --pass-policy all --fail-policy any --fail-after 300000000 \
        --dbus-ready-factor "$ready" --memory-latency "$latency" \
        "${sim_args[@]}" \
        "${rvls_args[@]}" \
        --name "shdlt_ctc_cpu${cpu}_${ctc_case}_${profile}_seed${seed}" >"$log" 2>&1
      python3 "$script_dir/ctc_report.py" "$log"
      logs+=("$log")
    done
  done
done
python3 "$script_dir/ctc_report.py" --campaign "${logs[@]}"
