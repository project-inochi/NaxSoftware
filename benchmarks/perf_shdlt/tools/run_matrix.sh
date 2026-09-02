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

cpu_arg=all
profile_arg=all
suite_arg=full
seed_override=
shard_index=0
shard_count=1
jobs=1
resume=0
dry_run=0
mode=architecture
output_root=
with_rvls=0

while (($#)); do
  case "$1" in
    --cpu) cpu_arg=${2:?--cpu requires 1, 2, 4, or all}; shift 2 ;;
    --profile) profile_arg=${2:?--profile requires a value}; shift 2 ;;
    --suite) suite_arg=${2:?--suite requires a value}; shift 2 ;;
    --seed) seed_override=${2:?--seed requires a value}; shift 2 ;;
    --shard)
      shard_index=${2%/*}; shard_count=${2#*/}; shift 2 ;;
    --jobs) jobs=${2:?--jobs requires a value}; shift 2 ;;
    --resume) resume=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    --hpm) mode=hpm; shift ;;
    --with-rvls|--rvls-check) with_rvls=1; shift ;;
    --no-rvls) with_rvls=0; shift ;;
    --observer|--legacy-observer)
      echo "legacy observer mode is unavailable in this TestBench build; use architecture or hpm" >&2
      exit 2
      ;;
    --mode) mode=${2:?--mode requires architecture or hpm}; shift 2 ;;
    --output-root) output_root=${2:?--output-root requires a path}; shift 2 ;;
    -h|--help)
      echo "usage: $0 [--cpu 1|2|4|all] [--profile baseline|pressure|severe|all]"
      echo "          [--suite throughput|latency|fault|freeze|full] [--seed N]"
      echo "          [--shard I/N] [--jobs N] [--resume] [--dry-run]"
      echo "          [--mode architecture|hpm] (default: architecture)"
      echo "          [--with-rvls|--rvls-check] (optional simulation diagnostic)"
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$mode" in
  architecture|hpm) ;;
  observer)
    echo "legacy observer mode is unavailable in this TestBench build; use architecture or hpm" >&2
    exit 2
    ;;
  *) echo "invalid --mode: $mode (expected architecture or hpm)" >&2; exit 2 ;;
esac
if [[ -z "$output_root" ]]; then
  mode_dir="$mode"
  ((with_rvls)) && mode_dir="${mode}_rvls"
  output_root="$test_dir/build/campaign/$mode_dir"
fi

case "$cpu_arg" in
  1) cpus=(1) ;;
  2) cpus=(2) ;;
  4) cpus=(4) ;;
  all) cpus=(1 2 4) ;;
  *) echo "invalid --cpu: $cpu_arg" >&2; exit 2 ;;
esac
case "$profile_arg" in
  baseline|pressure|severe) profiles=("$profile_arg") ;;
  all) profiles=(baseline pressure severe) ;;
  *) echo "invalid --profile: $profile_arg" >&2; exit 2 ;;
esac
case "$suite_arg" in
  throughput|latency|fault|freeze) suites=("$suite_arg") ;;
  full) suites=(throughput latency fault freeze) ;;
  *) echo "invalid --suite: $suite_arg" >&2; exit 2 ;;
esac
if ((shard_count < 1 || shard_index < 0 || shard_index >= shard_count)); then
  echo "--shard must be I/N with 0 <= I < N" >&2
  exit 2
fi
if ((jobs < 1)); then echo "--jobs must be positive" >&2; exit 2; fi

profile_parameters() {
  case "$1" in
    baseline) PROFILE_READY=1.01; PROFILE_LATENCY=0; PROFILE_SEED=2 ;;
    pressure) PROFILE_READY=0.70; PROFILE_LATENCY=17; PROFILE_SEED=3 ;;
    severe) PROFILE_READY=0.35; PROFILE_LATENCY=53; PROFILE_SEED=7 ;;
  esac
  if [[ -n "$seed_override" ]]; then PROFILE_SEED=$seed_override; fi
}

declare -a configs=()
add_config() {
  configs+=("$1|$2|$3|$4|$5|$6|$7|$8")
}

for profile in "${profiles[@]}"; do
  for cpu in "${cpus[@]}"; do
    if ((cpu == 1)); then caches=(l1 coherent_l1); phases=(single)
    else caches=(coherent_l1); phases=(same phase_shifted opposite)
    fi
    for suite in "${suites[@]}"; do
      case "$suite" in
        throughput)
          for cache in "${caches[@]}"; do
            for logger in off on; do
              for order in sequential reverse stride permuted; do
                for phase in "${phases[@]}"; do
                  for scaling in strong weak; do
                    add_config "$profile" "$cpu" "$cache" "$suite" "$logger" "$order" "$phase" "$scaling"
                  done
                done
              done
            done
          done
          ;;
        latency)
          phase=${phases[0]}
          for cache in "${caches[@]}"; do
            for logger in off on; do
              add_config "$profile" "$cpu" "$cache" "$suite" "$logger" sequential "$phase" weak
            done
          done
          ;;
        fault|freeze)
          phase=${phases[0]}
          for cache in "${caches[@]}"; do
            add_config "$profile" "$cpu" "$cache" "$suite" on sequential "$phase" weak
          done
          ;;
      esac
    done
  done
done

declare -a selected=()
for index in "${!configs[@]}"; do
  if ((index % shard_count == shard_index)); then selected+=("${configs[index]}"); fi
done

echo "SHDLT perf matrix total=${#configs[@]} shard=$shard_index/$shard_count selected=${#selected[@]}"
if ((dry_run)); then
  for config in "${selected[@]}"; do echo "$config"; done
  exit 0
fi

mkdir -p "$output_root"

declare -A compiled=()
hpm_build=off
[[ "$mode" == hpm ]] && hpm_build=on
for config in "${selected[@]}"; do
  IFS='|' read -r profile cpu cache suite logger order phase scaling <<<"$config"
  build_key="cpu${cpu}_${suite}_${logger}_${order}_${phase}_${scaling}"
  if [[ -z ${compiled[$build_key]+x} ]]; then
    obj_suffix=
    [[ "$mode" == hpm ]] && obj_suffix=_hpm
    objdir="$test_dir/build/elf/${build_key}${obj_suffix}"
    make -C "$test_dir" CPU_COUNT="$cpu" SUITE="$suite" LOGGER="$logger" \
      ORDER="$order" PHASE="$phase" SCALING="$scaling" \
      HPM="$hpm_build" OBJDIR="$objdir" compile
    compiled[$build_key]=1
  fi
done

run_one() {
  local config=$1
  local profile cpu cache suite logger order phase scaling
  IFS='|' read -r profile cpu cache suite logger order phase scaling <<<"$config"
  profile_parameters "$profile"
  local build_key="cpu${cpu}_${suite}_${logger}_${order}_${phase}_${scaling}"
  local hpm_value=off
  [[ "$mode" == hpm ]] && hpm_value=on
  local obj_suffix=
  [[ "$mode" == hpm ]] && obj_suffix=_hpm
  local elf="$test_dir/build/elf/${build_key}${obj_suffix}/perf_shdlt.elf"
  local diagnostic_suffix=
  ((with_rvls)) && diagnostic_suffix=_rvls
  local name="${profile}_${cache}_${build_key}_${mode}${diagnostic_suffix}_seed${PROFILE_SEED}"
  local log_dir="$output_root/$profile"
  local log="$log_dir/$name.log"
  local ok="$log.ok"
  mkdir -p "$log_dir"
  if ((resume)) && [[ -f "$ok" && -f "$log" ]]; then
    echo "SKIP $name"
    return 0
  fi
  printf 'SHDLT_PERF_RUN profile=%s cache=%s seed=0x%x ready=%s latency=0x%x hpm=%s\n' \
    "$profile" "$cache" "$PROFILE_SEED" "$PROFILE_READY" "$PROFILE_LATENCY" "$hpm_value" >"$log"
  local cache_args=(--with-lsu-l1)
  if [[ "$cache" == coherent_l1 ]]; then cache_args+=(--lsu-l1-coherency); fi
  local isa="h,m,a,c,svadu,shdlt,zicntr"
  local mode_args=(--seed "$PROFILE_SEED")
  # Keep the default campaign independent of the simulation-only RVLS
  # checker.  A user explicitly requesting the diagnostic may opt back in;
  # neither choice changes the firmware result ABI or the HPM measurements.
  if ((with_rvls == 0)); then mode_args+=(--no-rvls-check); fi
  if [[ "$mode" == hpm ]]; then
    isa+=",zihpm"
    mode_args+=(--performance-counters 4)
  fi
  echo "RUN $name"
  (
    cd "$repo_root"
    mill --no-server 'Test[2.13.12].runMain' vexiiriscv.tester.TestBench \
      --xlen 64 --cpu-count "$cpu" --reset-vector 0x80000000 \
      --with-isa "$isa" --with-fetch-l1 \
      "${cache_args[@]}" --load-elf "$elf" --pass-symbol pass --fail-symbol fail \
      --pass-policy all --fail-policy any --fail-after 10000000000 \
      --dbus-ready-factor "$PROFILE_READY" --memory-latency "$PROFILE_LATENCY" \
      "${mode_args[@]}" --name "$name"
  ) >>"$log" 2>&1
  if ((with_rvls)) && rg -i 'rvls.*mismatch|mismatch.*rvls' "$log" >/dev/null; then
    echo "RVLS mismatch in $log" >&2
    return 1
  fi
  report_args=()
  [[ "$mode" == hpm ]] && report_args+=(--require-hpm)
  python3 "$script_dir/perf_report.py" "${report_args[@]}" "$log"
  touch "$ok"
}

failures=0
declare -a pids=()
for config in "${selected[@]}"; do
  run_one "$config" &
  pids+=("$!")
  if ((${#pids[@]} >= jobs)); then
    if ! wait "${pids[0]}"; then failures=$((failures + 1)); fi
    pids=("${pids[@]:1}")
  fi
done
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then failures=$((failures + 1)); fi
done
if ((failures)); then
  echo "SHDLT perf matrix failures=$failures" >&2
  exit 1
fi

mapfile -t logs < <(find "$output_root" -name '*.log' -type f | sort)
if ((${#logs[@]})); then
  report_args=()
  [[ "$mode" == hpm ]] && report_args+=(--require-hpm)
  python3 "$script_dir/perf_report.py" "${report_args[@]}" \
    --output-dir "$output_root/report" "${logs[@]}"
fi
echo "SHDLT perf matrix PASS runs=${#selected[@]}"
