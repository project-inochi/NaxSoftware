#ifndef RTL_DIRECTED_SHDLT_RUNTIME_H
#define RTL_DIRECTED_SHDLT_RUNTIME_H

#define CSR_HGATP   0x680
#define CSR_HDLTCTL 0x681
#define CSR_HDLTIDX 0x682

#define HGATP_MODE_SV39X4 8ULL
#define MSTATUS_MPP_MASK  (3ULL << 11)
#define MSTATUS_MPP_HS    (1ULL << 11)
#define MSTATUS_MPV       (1ULL << 39)
#define MSTATUS_TVM       (1ULL << 20)
#define HSTATUS_SPV       (1ULL << 7)
#define SSTATUS_SPP       (1ULL << 8)

#define CAUSE_ILLEGAL_INSTRUCTION 2ULL
#define CAUSE_ECALL_HS            9ULL
#define CAUSE_ECALL_VS           10ULL
#define CAUSE_VIRTUAL_INSTRUCTION 22ULL

#define RTL_CASE_HGATP_RW_WARL       0
#define RTL_CASE_HGATP_PERMISSIONS   1
#define RTL_CASE_HDLTCTL_RW_WARL     2
#define RTL_CASE_HDLTIDX_MASK        3
#define RTL_CASE_HDLT_PERMISSIONS    4
#define RTL_CASE_COUNT               5

#define RTL_STATUS_VALUE       (1ULL << 0)
#define RTL_STATUS_MASK        (1ULL << 1)
#define RTL_STATUS_PERMISSION  (1ULL << 2)
#define RTL_STATUS_TRAP        (1ULL << 3)
#define RTL_STATUS_SIDE_EFFECT (1ULL << 4)
#define RTL_STATUS_UNEXPECTED  (1ULL << 5)

#ifndef __ASSEMBLER__

#include <stdint.h>

struct rtl_result {
  uint64_t abi_version;
  uint64_t case_id;
  uint64_t status;
  uint64_t hart_id;
  uint64_t reads;
  uint64_t writes;
  uint64_t expected;
  uint64_t actual;
  uint64_t trap_count;
  uint64_t trap_target;
  uint64_t cause;
  uint64_t epc;
  uint64_t tval;
  uint64_t mask_errors;
  uint64_t permission_errors;
  uint64_t side_effect_errors;
};

extern volatile uint64_t rtl_machine_phase;
extern volatile uint64_t rtl_vs_step;
extern volatile uint64_t rtl_failures;

void rtl_run_machine_tests(void);
void rtl_run_hs_tests(void);
void rtl_record_machine_trap(uint64_t cause, uint64_t epc, uint64_t tval);
void rtl_record_vs_trap(uint64_t cause, uint64_t epc, uint64_t tval);
void rtl_finish_from_hs(void) __attribute__((noreturn));

#endif
#endif
