import copy, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import pagefault_report as p

PPN=0x12345000
def event(case,rep):
    s=p.SPECS[case]; fault=s.fault
    before=PPN|s.fault_bits; restored=PPN|s.restore_bits
    a_before=0 if case in (17,18,21) else 1
    d_before=0 if case in (19,22) else 1
    values={
      "case":case,"id":case,"rep":rep,"stage":s.stage,"access":s.access,"fault_kind":fault,
      "expected_scause":s.scause,"actual_scause":s.scause if fault else 0,
      "expected_sepc":0x1940,"actual_sepc":0x1940 if fault else 0,
      "expected_stval":0x4000,"actual_stval":0x4000 if fault else 0,
      "expected_htval":0x800,"actual_htval":0x800 if fault else 0,
      "pte_table":s.stage,"pte_level":0,"pte_address":0x80204000,
      "pte_before":before,"pte_after_fault":PPN|s.fault_bits,"pte_after_restore":restored,
      "vs_a_before":a_before,"vs_a_after":1,"vs_d_before":d_before,"vs_d_after":1,
      "g_a_before":a_before,"g_a_after":1,"g_d_before":d_before,"g_d_after":1,
      "data_before":0x55,"data_after":0x55,"fault_count":fault,"resumed":1,
      "hfence_gvma":1,"hfence_vvma":1,"cycles":10,"instret":5,"status":0}
    return values
def records():
    begin={"version":1,"cases":23,"warmup":1,"reps":5,"case_first":0,"case_limit":23,"event_bytes":256,"summary_bytes":64}
    events=[event(c,r) for c in range(23) for r in range(1,6)]
    sums=[{"case":c,"rep":r,"status":0,"faults":p.SPECS[c].fault} for c in range(23) for r in range(1,6)]
    end={"completed":115,"failures":0,"status":0}
    return begin,events,sums,end
def line(kind,d): return "PAGEFAULT_"+kind+" "+" ".join(f"{k}=0x{v:x}" for k,v in d.items())
def text(rs=None):
    b,e,s,z=rs or records()
    lines=[]
    if b is not None: lines.append(line("BEGIN",b))
    lines.extend(line("EVENT",x) for x in e); lines.extend(line("SUMMARY",x) for x in s)
    if z is not None: lines.append(line("END",z))
    return "\n".join(lines)+"\n"

class ReportTests(unittest.TestCase):
    def assert_bad(self,mutator):
        rs=list(records()); mutator(rs)
        with self.assertRaises(ValueError): p.parse_text(text(rs))
    def test_valid(self): self.assertEqual(len(p.parse_text(text()).events),115)
    def test_noise_is_ignored(self): p.parse_text("boot\n"+text()+"tail\n")
    def test_missing_begin(self): self.assert_bad(lambda r:r.__setitem__(0,None))
    def test_missing_end(self): self.assert_bad(lambda r:r.__setitem__(3,None))
    def test_bad_version(self): self.assert_bad(lambda r:r[0].__setitem__("version",2))
    def test_bad_case_count(self): self.assert_bad(lambda r:r[0].__setitem__("cases",22))
    def test_bad_repetitions(self): self.assert_bad(lambda r:r[0].__setitem__("reps",4))
    def test_missing_event(self): self.assert_bad(lambda r:r[1].pop())
    def test_duplicate_event(self): self.assert_bad(lambda r:r[1].__setitem__(-1,copy.copy(r[1][0])))
    def test_bad_id(self): self.assert_bad(lambda r:r[1][0].__setitem__("id",1))
    def test_bad_stage(self): self.assert_bad(lambda r:r[1][0].__setitem__("stage",2))
    def test_bad_access(self): self.assert_bad(lambda r:r[1][0].__setitem__("access",2))
    def test_bad_expected_scause(self): self.assert_bad(lambda r:r[1][0].__setitem__("expected_scause",0x15))
    def test_bad_actual_scause(self): self.assert_bad(lambda r:r[1][0].__setitem__("actual_scause",0x15))
    def test_bad_sepc(self): self.assert_bad(lambda r:r[1][0].__setitem__("actual_sepc",0x1944))
    def test_bad_stval(self): self.assert_bad(lambda r:r[1][0].__setitem__("actual_stval",0x4004))
    def test_bad_htval(self): self.assert_bad(lambda r:r[1][0].__setitem__("actual_htval",0x801))
    def test_pte_ppn_changed(self): self.assert_bad(lambda r:r[1][0].__setitem__("pte_after_fault",r[1][0]["pte_after_fault"]+0x400))
    def test_fault_pte_changed(self): self.assert_bad(lambda r:r[1][0].__setitem__("pte_after_fault",PPN|0xd9))
    def test_restore_bits_changed(self): self.assert_bad(lambda r:r[1][0].__setitem__("pte_after_restore",PPN|0xd1))
    def test_missing_gvma_fence(self): self.assert_bad(lambda r:r[1][0].__setitem__("hfence_gvma",0))
    def test_missing_vvma_fence(self): self.assert_bad(lambda r:r[1][0].__setitem__("hfence_vvma",0))
    def test_missing_a_update(self): self.assert_bad(lambda r:r[1][85].__setitem__("vs_a_after",0))
    def test_missing_d_update(self): self.assert_bad(lambda r:r[1][95].__setitem__("g_d_after",0))
    def test_predirty_setup(self): self.assert_bad(lambda r:r[1][100].__setitem__("vs_d_before",0))
    def test_data_corruption(self): self.assert_bad(lambda r:r[1][0].__setitem__("data_after",0x56))
    def test_event_status(self): self.assert_bad(lambda r:r[1][0].__setitem__("status",1))
    def test_summary_status(self): self.assert_bad(lambda r:r[2][0].__setitem__("status",1))
    def test_summary_fault_count(self): self.assert_bad(lambda r:r[2][0].__setitem__("faults",0))
    def test_end_completed(self): self.assert_bad(lambda r:r[3].__setitem__("completed",114))
    def test_end_failures(self): self.assert_bad(lambda r:r[3].__setitem__("failures",1))
    def test_error_record(self):
        with self.assertRaises(ValueError): p.parse_text(text()+"PAGEFAULT_ERROR code=0x1\n")
    def test_duplicate_field(self):
        with self.assertRaises(ValueError): p.parse_text("PAGEFAULT_BEGIN version=0x1 version=0x1\n",False)
    def test_unknown_record(self):
        with self.assertRaises(ValueError): p.parse_text("PAGEFAULT_BOGUS x=0x1\n",False)

if __name__=="__main__": unittest.main()
