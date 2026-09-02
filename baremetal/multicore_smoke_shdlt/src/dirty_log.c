#include "runtime.h"
#include "dirty_log.h"

void shdlt_init_dirty_log(uint64_t hart) {
  volatile uint64_t *log = (volatile uint64_t *)(uintptr_t)DLT_BUFFER(hart);
  volatile uint64_t *ctl = (volatile uint64_t *)(uintptr_t)DLT_CONTROL(hart);
  for (unsigned i = 0; i < 512; i++) log[i] = 0;
  *ctl = 0;
}
