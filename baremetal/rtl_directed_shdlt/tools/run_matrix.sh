#!/bin/bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
test_dir=$(cd "$script_dir/.." && pwd)
repo_root=$test_dir
while [[ ! -f "$repo_root/build.mill" && "$repo_root" != / ]]; do
  repo_root=$(dirname "$repo_root")
done
if [[ ! -f "$repo_root/build.mill" ]]; then
  echo "could not locate VexiiRiscv build.mill" >&2
  exit 2
fi

selection=all
selection_explicit=0
# Accept the historical positional selector as well as options-first command
# lines (``run_matrix.sh --mode architecture smoke``).  This is only command
# line plumbing; it does not alter which ELF is selected.
if (($#)) && [[ "$1" != --* ]]; then
  selection=$1
  selection_explicit=1
  shift
fi
jobs=1
resume=0
shard_index=0
shard_count=1
mode=architecture
output_root=
while (($#)); do
  case "$1" in
    --jobs) jobs=${2:?--jobs requires a positive integer}; shift 2 ;;
    --resume) resume=1; shift ;;
    --shard)
      IFS=/ read -r shard_index shard_count <<<"${2:?--shard requires I/N}"
      shift 2
      ;;
    --mode) mode=${2:?--mode requires architecture or rvls}; shift 2 ;;
    --architecture-only|--no-rvls) mode=architecture; shift ;;
    --with-rvls|--rvls) mode=rvls; shift ;;
    --output-root) output_root=${2:?--output-root requires a path}; shift 2 ;;
    -h|--help)
      echo "usage: $0 [all|csr|dirtygen|smoke|race|ctc|verify]"
      echo "       [--jobs N] [--resume] [--shard I/N]"
      echo "       [--mode architecture|rvls] [--architecture-only|--with-rvls]"
      echo "       [--output-root PATH]"
      exit 0
      ;;
    --observer|--legacy-observer|--ctc-observer)
      echo "legacy observer mode is unavailable in this TestBench build; use the architectural result ABI" >&2
      exit 2
      ;;
    all|csr|dirtygen|smoke|race|ctc|verify)
      if ((selection_explicit)); then
        echo "duplicate campaign selector: $1" >&2
        exit 2
      fi
      selection=$1
      selection_explicit=1
      shift
      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if ! [[ "$jobs" =~ ^[1-9][0-9]*$ ]]; then echo "invalid --jobs: $jobs" >&2; exit 2; fi
case "$mode" in
  architecture|rvls) ;;
  observer)
    echo "legacy observer mode is unavailable in this TestBench build; use architecture or rvls" >&2
    exit 2
    ;;
  *) echo "invalid --mode: $mode (expected architecture or rvls)" >&2; exit 2 ;;
esac
if ! [[ "$shard_index" =~ ^[0-9]+$ && "$shard_count" =~ ^[1-9][0-9]*$ ]] || ((shard_index >= shard_count)); then
  echo "invalid --shard: $shard_index/$shard_count" >&2
  exit 2
fi
case "$selection" in
  all|csr|dirtygen|smoke|race|ctc|verify) ;;
  *) echo "usage: $0 {all|csr|dirtygen|smoke|race|ctc|verify} [--jobs N] [--resume] [--shard I/N] [--mode architecture|rvls]" >&2; exit 2 ;;
esac

manifest="$test_dir/binaries.sha256"
cd "$repo_root"
sha256sum -c "$manifest"
if [[ "$selection" == verify ]]; then exit 0; fi

make -C "$test_dir" compile

if [[ -z "$output_root" ]]; then
  output_root="$test_dir/build/campaign/$mode"
fi
log_dir="$output_root/logs"
trace_dir="$output_root/traces"
result_dir="$output_root/results"
mkdir -p "$log_dir" "$trace_dir" "$result_dir"
expected_file="$output_root/expected-shard${shard_index}-of-${shard_count}.txt"
: >"$expected_file"

smoke_cases=(load_only log_off predirty widths nonzero_index freeze reset_resume)
race_cases=(different_pages buffer_isolation same_pte same_cacheline_ptes)
ctc_cases=(pte_cache_hit_miss remote_pte_reread ownership_transfer coherence_pressure cas_retry \
           hfence_before_after hfence_gpa hfence_vmid hfence_global fence_hart_isolation)

specs=()
add_spec() { specs+=("$1|$2|$3|$4|$5|$6"); }

if [[ "$selection" == all || "$selection" == csr ]]; then
  add_spec csr 1 all baseline 2 "$test_dir/build/csr/rtl_directed_shdlt.elf"
fi
if [[ "$selection" == all || "$selection" == dirtygen ]]; then
  add_spec dirtygen 1 all baseline 2 "$repo_root/ext/NaxSoftware/benchmarks/dirtygen/build/dirtygen.elf"
fi
if [[ "$selection" == all || "$selection" == smoke ]]; then
  for cpu in 2 4; do
    for test_case in "${smoke_cases[@]}"; do
      if [[ "$cpu" == 2 ]]; then
        elf="$repo_root/ext/NaxSoftware/baremetal/multicore_smoke_shdlt/build/cpu2s_rv64gc_${test_case}_shdlt/multicore_smoke_shdlt.elf"
      else
        elf="$repo_root/ext/NaxSoftware/baremetal/multicore_smoke_shdlt/build/final4_${test_case}/multicore_smoke_shdlt.elf"
      fi
      add_spec smoke "$cpu" "$test_case" baseline 2 "$elf"
    done
  done
fi
if [[ "$selection" == all || "$selection" == race ]]; then
  for cpu in 2 4; do
    for test_case in "${race_cases[@]}"; do
      elf="$repo_root/ext/NaxSoftware/baremetal/multicore_race_shdlt/build/cpu${cpu}_${test_case}/multicore_race_shdlt.elf"
      add_spec race "$cpu" "$test_case" baseline 2 "$elf"
    done
  done
fi
if [[ "$selection" == all || "$selection" == ctc ]]; then
  for cpu in 2 4; do
    for test_case in "${ctc_cases[@]}"; do
      elf="$repo_root/ext/NaxSoftware/benchmarks/cache_tlb_shdlt/build/cpu${cpu}_${test_case}/cache_tlb_shdlt.elf"
      add_spec ctc "$cpu" "$test_case" baseline 2 "$elf"
    done
    for test_case in ownership_transfer coherence_pressure; do
      elf="$repo_root/ext/NaxSoftware/benchmarks/cache_tlb_shdlt/build/cpu${cpu}_${test_case}/cache_tlb_shdlt.elf"
      add_spec ctc "$cpu" "$test_case" severe 7 "$elf"
      add_spec ctc "$cpu" "$test_case" severe 11 "$elf"
    done
  done
fi

profile_values() {
  case "$1" in
    baseline) echo "1.01 0" ;;
    pressure) echo "0.70 17" ;;
    severe) echo "0.35 53" ;;
    *) return 1 ;;
  esac
}

run_one() {
  local family=$1 cpus=$2 test_case=$3 profile=$4 seed=$5 elf=$6 run_id=$7
  local log="$log_dir/$run_id.log"
  local trace="$trace_dir/$run_id.tracer.log"
  local result="$result_dir/$run_id.json"
  local done_file="$result_dir/$run_id.done"
  if ((resume)); then
    if [[ "$mode" == rvls && -f "$done_file" && -f "$result" && -f "$trace" &&
          -f "$result_dir/$run_id.invariants.json" ]]; then
      echo "RESUME $run_id"
      return 0
    fi
    if [[ "$mode" == architecture && -f "$done_file" && -f "$result" &&
          -f "$result_dir/$run_id.invariants.json" ]]; then
      echo "RESUME $run_id"
      return 0
    fi
  fi
  read -r ready latency < <(profile_values "$profile")
  local timeout=300000000
  [[ "$family" == csr ]] && timeout=10000000
  [[ "$family" == dirtygen ]] && timeout=2000000000
  local name="shdlt_rtl_${run_id}"
  local args=(
    --xlen 64 --cpu-count "$cpus" --physical-width 32 --reset-vector 0x80000000
    --with-isa h,m,a,c,svadu,shdlt,zicntr
    --with-fetch-l1 --with-lsu-l1
    --load-elf "$elf" --pass-symbol pass --fail-symbol fail
    --pass-policy all --fail-policy any --fail-after "$timeout"
    --dbus-ready-factor "$ready" --memory-latency "$latency" --seed "$seed"
    --name "$name"
  )
  if [[ "$mode" == rvls ]]; then
    args+=(--with-rvls-log)
  else
    # The architecture-only path deliberately disables the optional RVLS
    # checker.  TestBench still executes the same public ISA/CSR/cache paths;
    # only the simulation-side diagnostic backend is absent.
    args+=(--no-rvls-check)
  fi
  if ((cpus > 1)); then args+=(--lsu-l1-coherency); fi
  echo "RUN $run_id"
  if ! mill --no-server 'Test[2.13.12].runMain' vexiiriscv.tester.TestBench "${args[@]}" >"$log" 2>&1; then
    echo "FAIL $run_id (simulation), see $log" >&2
    return 1
  fi
  if [[ "$mode" == rvls ]]; then
    local source_trace="$repo_root/simWorkspace/TestBenchDut/$name/tracer.log"
    if [[ ! -f "$source_trace" ]]; then
      echo "FAIL $run_id (missing tracer.log at $source_trace)" >&2
      return 1
    fi
    cp "$source_trace" "$trace"
  fi
  case "$family" in
    dirtygen)
      python3 "$repo_root/ext/NaxSoftware/benchmarks/dirtygen/tools/dirtygen_report.py" "$log" --format json >"$result_dir/$run_id.arch.json"
      ;;
    race)
      python3 "$repo_root/ext/NaxSoftware/baremetal/multicore_race_shdlt/tools/race_report.py" "$log" --format json >"$result_dir/$run_id.arch.json"
      ;;
    ctc)
      python3 "$repo_root/ext/NaxSoftware/benchmarks/cache_tlb_shdlt/tools/ctc_report.py" \
        --format json "$log" >"$result_dir/$run_id.arch.json"
      ;;
  esac
  report_args=(--family "$family" --cpus "$cpus" --case "$test_case" --log "$log" --json "$result")
  invariant_args=(--family "$family" --cpus "$cpus" --case "$test_case" \
                  --json "$result_dir/$run_id.invariants.json")
  if [[ "$mode" == rvls ]]; then
    report_args+=(--trace "$trace" --require-trace)
    invariant_args+=(--trace "$trace" --require-trace)
  fi
  python3 "$script_dir/rtl_report.py" "${report_args[@]}" >/dev/null
  if [[ -f "$result_dir/$run_id.arch.json" ]]; then
    invariant_args+=(--arch "$result_dir/$run_id.arch.json")
  fi
  python3 "$script_dir/invariant_report.py" "${invariant_args[@]}" >/dev/null
  touch "$done_file"
  echo "PASS $run_id"
}

selected=()
for index in "${!specs[@]}"; do
  ((index % shard_count == shard_index)) || continue
  IFS='|' read -r family cpus test_case profile seed elf <<<"${specs[$index]}"
  run_id="${family}_cpu${cpus}_${test_case}_${profile}_seed${seed}"
  selected+=("${specs[$index]}|$run_id")
  printf '%s\n' "$run_id" >>"$expected_file"
done
if ((${#selected[@]} == 0)); then
  echo "selected shard is empty" >&2
  exit 2
fi

failures=0
active=0
for selected_spec in "${selected[@]}"; do
  IFS='|' read -r family cpus test_case profile seed elf run_id <<<"$selected_spec"
  run_one "$family" "$cpus" "$test_case" "$profile" "$seed" "$elf" "$run_id" &
  ((active += 1))
  if ((active >= jobs)); then
    if ! wait -n; then failures=1; fi
    active=$((active - 1))
  fi
done
while ((active > 0)); do
  if ! wait -n; then failures=1; fi
  active=$((active - 1))
done
if ((failures)); then
  echo "one or more campaign simulations failed" >&2
  exit 1
fi

sha256sum -c "$manifest"
python3 "$script_dir/campaign_report.py" --expected "$expected_file" \
  --results "$result_dir" --json "$output_root/summary-shard${shard_index}-of-${shard_count}.json" \
  --text "$output_root/summary-shard${shard_index}-of-${shard_count}.txt"
