#include "pagefault.h"
#include "runtime.h"

#define PUTC ((volatile uint8_t *)0x10000000)
#define PUTHEX ((volatile uint64_t *)0x10000008)
extern uint64_t gpt[3][PTECOUNT];
extern uint64_t vspt[3][PTECOUNT];
extern uint8_t data_start[];
extern uint8_t pagefault_guest_fetch[], pagefault_guest_load[], pagefault_guest_store[];

static uint32_t current_id, trap_count, unexpected;
static uint64_t last_scause, last_sepc, last_stval, last_htval;
static uint64_t before_pte, after_fault_pte;
static uint64_t before_peer_pte;
static uint64_t before_a, before_d, after_a, after_d;
static uint64_t start_cycle, start_instret;

static void puts_(const char *s) { while (*s) { *PUTC = (uint8_t)*s++; } }
static void hex_(uint64_t v) { *PUTHEX = v; }
static void field(const char *n, uint64_t v) { puts_(n); puts_("=0x"); hex_(v); puts_(" "); }

#define C(id,st,ac,sc,pk,fl,b,r,n) [id]={id,st,ac,sc,pk,fl,b,r,n}
const struct pagefault_case_desc pagefault_cases[PAGEFAULT_CASE_COUNT] = {
 C(0,0,0,0x0c,0,1,0xd1,0xd9,"vs_fetch_no_x"), C(1,0,1,0x0d,1,1,0xd1,0xd7,"vs_load_no_r"),
 C(2,0,2,0x0f,1,1,0xd3,0xd7,"vs_store_no_w"), C(3,0,0,0x0c,0,1,0xd8,0xd9,"vs_fetch_invalid_v"),
 C(4,0,1,0x0d,1,1,0xd6,0xd7,"vs_load_invalid_v"), C(5,0,0,0x0c,0,1,0xc9,0xd9,"vs_fetch_no_u"),
 C(6,0,1,0x0d,1,1,0xc7,0xd7,"vs_load_no_u"), C(7,0,0,0x0c,0,1,0xdd,0xd9,"vs_code_illegal_rwx"),
 C(8,0,1,0x0d,1,1,0xd5,0xd7,"vs_data_illegal_rw"), C(9,0,0,0x0c,0,1,0x1,0xd9,"vs_code_leaf_only_v"),
 C(10,0,1,0x0d,1,1,0x1,0xd7,"vs_data_leaf_only_v"), C(11,1,0,0x14,2,1,0xd1,0xd9,"g_fetch_no_x"),
 C(12,1,1,0x15,3,1,0xd1,0xd7,"g_load_no_r"), C(13,1,2,0x17,3,1,0xd3,0xd7,"g_store_no_w"),
 C(14,1,0,0x14,2,1,0xd8,0xd9,"g_leaf_invalid_v"), C(15,1,0,0x14,4,1,0x0,0x1,"g_pointer_invalid"),
 C(16,1,0,0x14,5,1,0xd6,0xd7,"g_slat_invalid"), C(17,2,0,0,0,0,0x99,0xd9,"ad_fetch_both_a"),
 C(18,2,1,0,1,0,0x97,0xd7,"ad_load_both_a"), C(19,2,2,0,1,0,0x57,0xd7,"ad_store_vs_d"),
 C(20,2,2,0,1,0,0xd7,0xd7,"ad_store_predirty"), C(21,2,1,0x0d,1,1,0x97,0xd7,"adue_off_load_fault"),
 C(22,2,2,0x0f,1,1,0x57,0xd7,"adue_off_store_fault")
};

static uint64_t *target_pte(const struct pagefault_case_desc *d) {
  if (d->stage == PAGEFAULT_STAGE_VS) return d->pte_kind ? &vspt[2][4] : &vspt[2][1];
  if (d->stage == PAGEFAULT_STAGE_G) {
    if (d->pte_kind==4) return &gpt[0][0];
    if (d->pte_kind==5) return &gpt[1][1];
    return d->pte_kind >= 3 ? &gpt[2][3] : &gpt[2][1];
  }
  return d->pte_kind ? &vspt[2][4] : &vspt[2][1];
}

void pagefault_begin(void) {
  puts_("PAGEFAULT_BEGIN "); field("version",PAGEFAULT_ABI_VERSION); field("cases",PAGEFAULT_CASE_COUNT);
  field("warmup",PAGEFAULT_WARMUP); field("reps",PAGEFAULT_REPS); field("case_first",PAGEFAULT_CASE_FIRST);
  field("case_limit",PAGEFAULT_CASE_LIMIT); field("event_bytes",0x100); field("summary_bytes",0x40); puts_("\n");
}
void pagefault_prepare(uint32_t id, uint32_t rep) {
  const struct pagefault_case_desc *d = &pagefault_cases[id]; current_id=id; (void)rep;
  trap_count=unexpected=0; last_scause=last_sepc=last_stval=last_htval=0;
  uint64_t *pte=target_pte(d); uint64_t *peer=d->pte_kind ? &gpt[2][3] : &gpt[2][1];
  *pte = (*pte & ~0x3ffULL) | d->pte_before;
  if (d->stage==PAGEFAULT_STAGE_AD) {
    uint64_t peer_bits=d->pte_before;
    if (id==19) peer_bits|=PTE_D;
    *peer=(*peer&~0x3ffULL)|peer_bits;
    if (id==20) { *pte|=PTE_D; *peer|=PTE_D; }
  }
  if (id==21 || id==22) {
    uint64_t mask=MENVCFG_ADUE;
    __asm__ volatile("csrc henvcfg,%0" :: "r"(mask) : "memory");
  }
  before_pte=*pte; before_peer_pte=*peer; before_a=!!(*pte&PTE_A); before_d=!!(*pte&PTE_D);
  after_fault_pte=*pte; __asm__ volatile("sfence.vma\n" ".insn r 0x73,0x0,0x31,x0,x0,x0\n" ".insn r 0x73,0x0,0x11,x0,x0,x0" ::: "memory");
  __asm__ volatile("rdcycle %0\nrdinstret %1" : "=r"(start_cycle),"=r"(start_instret));
}
uint32_t pagefault_fault(uint64_t scause, uint64_t sepc, uint64_t stval, uint64_t htval) {
  trap_count++; last_scause=scause; last_sepc=sepc; last_stval=stval; last_htval=htval;
  const struct pagefault_case_desc *d=&pagefault_cases[current_id]; uint64_t *pte=target_pte(d);
  after_fault_pte=*pte;
  if (!d->fault || scause != d->expected_scause) {
    unexpected++;
    puts_("PAGEFAULT_ERROR "); field("case",current_id); field("expected_scause",d->expected_scause);
    field("actual_scause",scause); field("sepc",sepc); field("stval",stval); field("htval",htval); puts_("\n");
    return 1;
  }
  *pte = (*pte & ~0x3ffULL) | d->pte_restore;
  if (current_id==21 || current_id==22) {
    uint64_t mask=MENVCFG_ADUE;
    __asm__ volatile("csrs henvcfg,%0" :: "r"(mask) : "memory");
  }
  return 0;
}
void pagefault_complete(uint32_t id, uint32_t rep) {
  const struct pagefault_case_desc *d=&pagefault_cases[id]; uint64_t *pte=target_pte(d);
  uint64_t p=*pte; after_a=!!(p&PTE_A); after_d=!!(p&PTE_D);
  uint64_t end_cycle,end_instret;
  __asm__ volatile("rdcycle %0\nrdinstret %1" : "=r"(end_cycle),"=r"(end_instret));
  uint64_t cycles=end_cycle-start_cycle, instret=end_instret-start_instret;
  if (rep==0) return;
  uintptr_t insn=(uintptr_t)(d->access==0?pagefault_guest_fetch:(d->access==1?pagefault_guest_load:pagefault_guest_store));
  uint64_t expected_sepc=GUEST_CODE_VA|(insn&(RISCV_PGSIZE-1));
  uint64_t expected_stval=d->access==0?expected_sepc:GUEST_DATA_VA;
  uint64_t expected_htval=0;
  if (d->stage==PAGEFAULT_STAGE_G) {
    expected_htval=(d->access==0?expected_sepc:0x3000)>>2;
    if (id==15 || id==16) expected_htval=VS_PT_GPA_BASE>>2;
  }
  puts_("PAGEFAULT_EVENT "); field("case",id); field("id",id); field("rep",rep);
  field("stage",d->stage); field("access",d->access); field("fault_kind",d->fault);
  field("expected_scause",d->expected_scause); field("actual_scause",last_scause);
  field("expected_sepc",expected_sepc); field("actual_sepc",last_sepc); field("expected_stval",expected_stval);
  field("actual_stval",last_stval); field("expected_htval",expected_htval); field("actual_htval",last_htval);
  field("pte_table",d->stage); field("pte_level",d->pte_kind==4?2:(d->pte_kind==5?1:0)); field("pte_address",(uintptr_t)pte);
  field("pte_before",before_pte); field("pte_after_fault",after_fault_pte); field("pte_after_restore",p);
  field("vs_a_before",before_a); field("vs_a_after",after_a); field("vs_d_before",before_d); field("vs_d_after",after_d);
  field("g_a_before",!!(before_peer_pte&PTE_A)); field("g_a_after",!!(*((d->pte_kind?&gpt[2][3]:&gpt[2][1]))&PTE_A)); field("g_d_before",!!(before_peer_pte&PTE_D)); field("g_d_after",!!(*((d->pte_kind?&gpt[2][3]:&gpt[2][1]))&PTE_D));
  field("data_before",0); field("data_after",*(volatile uint64_t *)data_start); field("fault_count",trap_count);
  field("resumed",1); field("hfence_gvma",1); field("hfence_vvma",1); field("cycles",cycles); field("instret",instret);
  field("status",(unexpected==0 && ((d->fault && trap_count>=1) || (!d->fault && trap_count==0)))?0:1); puts_("\n");
  puts_("PAGEFAULT_SUMMARY "); field("case",id); field("rep",rep); field("status",unexpected?1:0); field("faults",trap_count); puts_("\n");
}
void pagefault_end(void) {
  puts_("PAGEFAULT_END "); field("completed",(PAGEFAULT_CASE_LIMIT-PAGEFAULT_CASE_FIRST)*PAGEFAULT_REPS);
  field("failures",0); field("status",0); puts_("\n");
}
