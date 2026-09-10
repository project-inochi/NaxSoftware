/* Host-executable test of the same raw-word check used by corrected firmware. */
#include "shdlt_isa.h"
int main(void) {
  const uint64_t gpa = UINT64_C(0x40000);
  if (!shdlt_isa_log_word_valid(gpa)) return 1;
  for (unsigned bit = 0; bit < 64; ++bit) {
    if ((bit < 12 || bit >= 56) && shdlt_isa_log_word_valid(gpa | (UINT64_C(1) << bit))) return 2;
  }
  return 0;
}
