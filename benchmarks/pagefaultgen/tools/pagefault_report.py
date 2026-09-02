#!/usr/bin/env python3
"""Parse and strictly validate the standalone PAGEFAULT ABI v1 stream."""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ABI_VERSION=1; CASE_COUNT=23; WARMUP=1; REPS=5; EVENT_BYTES=256; SUMMARY_BYTES=64
PREFIX="PAGEFAULT_"; PTE_MASK=0x3ff

@dataclass(frozen=True)
class CaseSpec:
    name:str; stage:int; access:int; scause:int; fault:int; fault_bits:int; restore_bits:int

SPECS=(
 CaseSpec("vs_fetch_no_x",0,0,0x0c,1,0xd1,0xd9), CaseSpec("vs_load_no_r",0,1,0x0d,1,0xd1,0xd7),
 CaseSpec("vs_store_no_w",0,2,0x0f,1,0xd3,0xd7), CaseSpec("vs_fetch_invalid_v",0,0,0x0c,1,0xd8,0xd9),
 CaseSpec("vs_load_invalid_v",0,1,0x0d,1,0xd6,0xd7), CaseSpec("vs_fetch_no_u",0,0,0x0c,1,0xc9,0xd9),
 CaseSpec("vs_load_no_u",0,1,0x0d,1,0xc7,0xd7), CaseSpec("vs_code_illegal_rwx",0,0,0x0c,1,0xdd,0xd9),
 CaseSpec("vs_data_illegal_rw",0,1,0x0d,1,0xd5,0xd7), CaseSpec("vs_code_leaf_only_v",0,0,0x0c,1,1,0xd9),
 CaseSpec("vs_data_leaf_only_v",0,1,0x0d,1,1,0xd7), CaseSpec("g_fetch_no_x",1,0,0x14,1,0xd1,0xd9),
 CaseSpec("g_load_no_r",1,1,0x15,1,0xd1,0xd7), CaseSpec("g_store_no_w",1,2,0x17,1,0xd3,0xd7),
 CaseSpec("g_leaf_invalid_v",1,0,0x14,1,0xd8,0xd9), CaseSpec("g_pointer_invalid",1,0,0x14,1,0,1),
 CaseSpec("g_slat_invalid",1,0,0x14,1,0xd6,0xd7), CaseSpec("ad_fetch_both_a",2,0,0,0,0x99,0xd9),
 CaseSpec("ad_load_both_a",2,1,0,0,0x97,0xd7), CaseSpec("ad_store_vs_d",2,2,0,0,0x57,0xd7),
 CaseSpec("ad_store_predirty",2,2,0,0,0xd7,0xd7), CaseSpec("adue_off_load_fault",2,1,0x0d,1,0x97,0xd7),
 CaseSpec("adue_off_store_fault",2,2,0x0f,1,0x57,0xd7),
)
EVENT_FIELDS=("case","id","rep","stage","access","fault_kind","expected_scause","actual_scause",
 "expected_sepc","actual_sepc","expected_stval","actual_stval","expected_htval","actual_htval",
 "pte_table","pte_level","pte_address","pte_before","pte_after_fault","pte_after_restore",
 "vs_a_before","vs_a_after","vs_d_before","vs_d_after","g_a_before","g_a_after","g_d_before","g_d_after",
 "data_before","data_after","fault_count","resumed","hfence_gvma","hfence_vvma","cycles","instret","status")

def _value(v:str)->Any:
    return int(v,16) if v.startswith("0x") else v
def _record(line:str):
    pos=line.find(PREFIX)
    if pos<0:return None
    tokens=line[pos:].strip().split(); kind=tokens[0][len(PREFIX):].lower(); out={}
    for token in tokens[1:]:
        if "=" not in token: raise ValueError(f"malformed PAGEFAULT token {token!r}")
        k,v=token.split("=",1)
        if k in out: raise ValueError(f"duplicate PAGEFAULT field {k!r}")
        out[k]=_value(v)
    return kind,out
def _num(r:dict[str,Any],k:str,kind:str)->int:
    v=r.get(k)
    if not isinstance(v,int): raise ValueError(f"{kind} is missing numeric field {k!r}")
    return v

@dataclass
class PagefaultReport:
    begin:dict[str,Any]|None=None; end:dict[str,Any]|None=None
    events:list[dict[str,Any]]=field(default_factory=list)
    summaries:list[dict[str,Any]]=field(default_factory=list)
    errors:list[dict[str,Any]]=field(default_factory=list)
    def validate(self)->None:
        if self.begin is None: raise ValueError("missing PAGEFAULT_BEGIN")
        if self.end is None: raise ValueError("missing PAGEFAULT_END")
        if self.errors: raise ValueError(f"pagefaultgen emitted {len(self.errors)} error record(s)")
        expected={"version":ABI_VERSION,"cases":CASE_COUNT,"warmup":WARMUP,"reps":REPS,"event_bytes":EVENT_BYTES,"summary_bytes":SUMMARY_BYTES}
        for k,v in expected.items():
            if _num(self.begin,k,"PAGEFAULT_BEGIN")!=v: raise ValueError(f"PAGEFAULT_BEGIN {k} mismatch")
        first=_num(self.begin,"case_first","PAGEFAULT_BEGIN"); limit=_num(self.begin,"case_limit","PAGEFAULT_BEGIN")
        if first<0 or first>=limit or limit>CASE_COUNT: raise ValueError("PAGEFAULT_BEGIN case range is invalid")
        keys={(c,r) for c in range(first,limit) for r in range(1,REPS+1)}
        if len(self.events)!=len(keys): raise ValueError(f"expected {len(keys)} PAGEFAULT_EVENT records, got {len(self.events)}")
        seen=set()
        for event in self.events:
            for name in EVENT_FIELDS:_num(event,name,"PAGEFAULT_EVENT")
            key=(_num(event,"case","PAGEFAULT_EVENT"),_num(event,"rep","PAGEFAULT_EVENT"))
            if key in seen: raise ValueError(f"duplicate PAGEFAULT_EVENT {key}")
            seen.add(key)
            case,rep=key
            if case>=CASE_COUNT or rep<1 or rep>REPS: raise ValueError(f"out-of-range PAGEFAULT_EVENT {key}")
            s=SPECS[case]
            checks={"id":case,"stage":s.stage,"access":s.access,"fault_kind":s.fault,"expected_scause":s.scause,
                    "actual_scause":s.scause if s.fault else 0,"fault_count":s.fault,"resumed":1,
                    "hfence_gvma":1,"hfence_vvma":1,"status":0}
            for name,value in checks.items():
                if event[name]!=value: raise ValueError(f"case {case} rep {rep}: {name} mismatch")
            if s.fault:
                for suffix in ("sepc","stval","htval"):
                    if event[f"actual_{suffix}"]!=event[f"expected_{suffix}"]:
                        raise ValueError(f"case {case} rep {rep}: {suffix} mismatch")
            elif any(event[x] for x in ("actual_scause","actual_sepc","actual_stval","actual_htval")):
                raise ValueError(f"case {case} rep {rep}: unexpected trap metadata")
            before=event["pte_before"]; fault=event["pte_after_fault"]; restored=event["pte_after_restore"]
            if (before>>10)!=(fault>>10) or (before>>10)!=(restored>>10):
                raise ValueError(f"case {case} rep {rep}: PTE PPN changed")
            if (fault&PTE_MASK)!=s.fault_bits: raise ValueError(f"case {case} rep {rep}: fault PTE bits mismatch")
            if s.fault and fault!=before: raise ValueError(f"case {case} rep {rep}: fault implicitly modified PTE")
            if s.fault and (restored&PTE_MASK)!=s.restore_bits: raise ValueError(f"case {case} rep {rep}: restore PTE bits mismatch")
            if event["data_before"]!=event["data_after"]: raise ValueError(f"case {case} rep {rep}: data changed")
            if case in (17,18,21) and (event["vs_a_after"]!=1 or event["g_a_after"]!=1):
                raise ValueError(f"case {case} rep {rep}: A update missing")
            if case in (19,20,22) and (event["vs_d_after"]!=1 or event["g_d_after"]!=1):
                raise ValueError(f"case {case} rep {rep}: D update missing")
            if case==20 and (event["vs_d_before"]!=1 or event["g_d_before"]!=1):
                raise ValueError(f"case {case} rep {rep}: predirty setup missing")
        if seen!=keys: raise ValueError(f"missing PAGEFAULT_EVENT records: {sorted(keys-seen)}")
        if len(self.summaries)!=len(keys): raise ValueError(f"expected {len(keys)} PAGEFAULT_SUMMARY records")
        sums=set()
        for s in self.summaries:
            key=(_num(s,"case","PAGEFAULT_SUMMARY"),_num(s,"rep","PAGEFAULT_SUMMARY"))
            if key in sums: raise ValueError(f"duplicate PAGEFAULT_SUMMARY {key}")
            sums.add(key)
            if _num(s,"status","PAGEFAULT_SUMMARY")!=0: raise ValueError(f"PAGEFAULT_SUMMARY {key} failed")
            if _num(s,"faults","PAGEFAULT_SUMMARY")!=SPECS[key[0]].fault: raise ValueError(f"PAGEFAULT_SUMMARY {key} fault mismatch")
        if sums!=keys: raise ValueError("PAGEFAULT_SUMMARY coverage mismatch")
        end_expected={"completed":len(keys),"failures":0,"status":0}
        for k,v in end_expected.items():
            if _num(self.end,k,"PAGEFAULT_END")!=v: raise ValueError(f"PAGEFAULT_END {k} mismatch")

def parse_text(text:str,validate:bool=True)->PagefaultReport:
    report=PagefaultReport()
    for line in text.splitlines():
        item=_record(line)
        if item is None:continue
        kind,data=item
        if kind=="begin":
            if report.begin is not None: raise ValueError("duplicate PAGEFAULT_BEGIN")
            report.begin=data
        elif kind=="end":
            if report.end is not None: raise ValueError("duplicate PAGEFAULT_END")
            report.end=data
        elif kind=="event":report.events.append(data)
        elif kind=="summary":report.summaries.append(data)
        elif kind=="error":report.errors.append(data)
        else: raise ValueError(f"unknown PAGEFAULT record {kind!r}")
    if validate:report.validate()
    return report

def main(argv=None)->int:
    p=argparse.ArgumentParser(); p.add_argument("log",type=Path); p.add_argument("--format",choices=("table","json"),default="table")
    a=p.parse_args(argv)
    try:r=parse_text(a.log.read_text(errors="replace"))
    except (OSError,ValueError) as e: print(f"pagefault report error: {e}",file=sys.stderr); return 1
    if a.format=="json": print(json.dumps({"begin":r.begin,"events":r.events,"summaries":r.summaries,"end":r.end},indent=2))
    else:
        print("case  name                       events  faults  status")
        first=r.begin["case_first"]; limit=r.begin["case_limit"]
        for i in range(first,limit):
            s=SPECS[i]
            ev=[e for e in r.events if e["case"]==i]
            print(f"{i:>4}  {s.name:<26} {len(ev):>6}  {sum(e['fault_count'] for e in ev):>6}  PASS")
        print(f"completed={r.end['completed']} failures={r.end['failures']} status=PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
